# jsonパッケージを使うためのインポート
# reパッケージは正規表現用
# subprocessは外部コマンド実行用
# sysは終了処理用
# pathlibはパス操作用
import json
import re
import subprocess
import sys
from pathlib import Path

from openai_codex import Codex, Sandbox


# Codexに返してほしい答えの形（JSON Schema）。この形以外では返ってこない
PR_SCHEMA = {
    "type": "object",
    "properties": {
        "branch": {"type": "string", "description": "英小文字・数字・ハイフンだけの短いブランチ名。例: fix-average"},
        "commit_message": {"type": "string", "description": "日本語1行のコミットメッセージ"},
        "title": {"type": "string", "description": "日本語のPRのタイトル"},
        "what": {"type": "string", "description": "何を変えたか（箇条書き可）"},
        "why": {"type": "string", "description": "なぜ変えたか"},
        "how_checked": {"type": "string", "description": "どう確かめたか。確かめていなければ、確かめ方の案"},
    },
    "required": ["branch", "commit_message", "title", "what", "why", "how_checked"],
    "additionalProperties": False,
}

MAX_DIFF = 30000  # 差分が長すぎるときは、ここで切る

def git(folder, *args):
    """git を打って出力を返す。失敗したら、そこで止める"""
    r = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} が失敗しました:\n{r.stderr}")
    return r.stdout


def safety_check(folder):
    """push-mae-check を Python で。AIに任せず、毎回かならず通す"""
    status = git(folder, "status", "--porcelain", "--untracked-files=all")
    if not status.strip():
        sys.exit("変更がありません")
    for line in status.splitlines():
        path = line[3:]
        if Path(path).name == ".env" or path.startswith(".venv/"):
            sys.exit(f"止めました：{path} が上がりそうです。.gitignore を確かめてください")

    git(folder, "add", "-A")  # 上げる準備（新しいファイルも中身を見られるようにする）
    diff = git(folder, "diff", "--cached")
    if re.search(r"sk-[A-Za-z0-9_-]{20,}", diff):
        git(folder, "reset")  # 上げる準備を取り消す（ファイルの中身はそのまま）
        sys.exit("止めました：差分に sk- で始まるキーのような文字があります")
    return diff

def ask_codex(folder, diff, request):
    """考えるのはCodex。ブランチ名・タイトル・説明文を、決まった形で書いてもらう"""
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + "\n（長いので、ここで切りました）"
    prompt = f"""次の変更をPRにします。PRの中身を考えてください。
ファイルの変更・コミット・pushはしないでください（それはこちらでやります）。

頼んだ人のひとこと：{request}

--- 変更（git diff）---

{diff}
"""
    with Codex() as codex:
        # 差分はプロンプトに入れてあるので、読むだけ（read_only）で足りる
        thread = codex.thread_start(cwd=folder, sandbox=Sandbox.read_only)
        result = thread.run(prompt, output_schema=PR_SCHEMA)
    if not result.final_response:
        sys.exit("Codexが答えを返さずに終わりました。もう一度ためしてください")
    return json.loads(result.final_response)

def main():
    # 絶対パスに変換する
    folder = str(Path(sys.argv[1] if len(sys.argv) > 1 else ".").expanduser().resolve())
    # PR作成の依頼内容を取得する
    # 第二引数として依頼内容を受け取る
    # これってなにもなかったら自動で "PR作成よろしく" にするってこと？→あってそう。
    request = sys.argv[2] if len(sys.argv) > 2 else "PR作成よろしく"

    # 第一引数はフォルダ、第二引数は依頼内容
    diff = safety_check(folder)
    print("Codexが説明文を考えています…")
    info = ask_codex(folder, diff, request)

    body = (
        f"## 何を変えたか\n{info['what']}\n\n"
        f"## なぜ\n{info['why']}\n\n"
        f"## どう確かめたか\n{info['how_checked']}\n\n"
        "---\npr-yoroshiku（Codex SDK）で作りました"
    )
    current = git(folder, "rev-parse", "--abbrev-ref", "HEAD").strip()
    branch = info["branch"] if current in ("main", "master") else current
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", branch):
        branch = "pr-yoroshiku"

    print(f"\nブランチ：{branch}\nコミット：{info['commit_message']}\nタイトル：{info['title']}\n\n{body}\n")
    if input("この内容でPRを作っていい？ (y/n) ").strip().lower() != "y":
        git(folder, "reset")
        print("やめました。ファイルの変更はそのままです")
        return

    # 手を動かすのはPython。決まった順番で、毎回同じように打つ
    if branch != current:
        git(folder, "switch", "-c", branch)
    git(folder, "commit", "-m", info["commit_message"])
    git(folder, "push", "-u", "origin", branch)
    r = subprocess.run(
        ["gh", "pr", "create", "--title", info["title"], "--body", body, "--head", branch],
        cwd=folder, capture_output=True, text=True,
    )
    print(r.stdout.strip() or r.stderr.strip())


if __name__ == "__main__":
    main()
# そもそもこのスクリプトはなんなのか？
# Gitの変更をもとに、PRの説明文やブランチ名、コミットメッセージを自動で考えてくれるツールです。
# 実際のファイルの変更やコミット、pushはPythonが行い、PRの作成も自動で行います。

# 実行したこと python pr.py
# 起きたこと
# 第二引数になにも入れなかったから、requestは "PR作成よろしく" になった
# Codexが説明文を考えますが走る
# その後、PRの内容が表示され、確認を求められる