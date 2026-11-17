import json
import subprocess
import sys
from pathlib import Path

from openai_codex import Codex, Sandbox

# 指摘の形。1つの指摘＝どのファイルの何行目に、どのくらい大事な、何の話か
# codexに返してほしい答えの形を決めた設計書
# JSON Schemaという規格に沿った形式でCodexにレビューを依頼するための設計書

### PRレビューのJSON Schema
REVIEW_SCHEMA = {
    ### PRレビューのJSON Schema
    ### type 値の種類
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "このPRを1〜2文で"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer", "description": "変更後のファイルの行番号"},
                    "severity": {"type": "string", "enum": ["must", "should", "nit"]},
                    "message": {"type": "string", "description": "何が問題か"},
                    "suggestion": {"type": "string", "description": "どう直すとよいか"},
                },
                "required": ["file", "line", "severity", "message", "suggestion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "findings"],
    "additionalProperties": False,
}

LABEL = {"must": "直してほしい", "should": "できれば", "nit": "細かいこと"}


# GitHub CLI を使うための関数
# ここ、命名微妙じゃない？
# ghってなにって話だよね。
# この関数ってなにしているの？
# folder指定しているのはわかる。この引数はなんでこんな書き方をしているの？

## pythonの中からghコマンドを実行して、その結果を返す関数。
## print文で確認すること。
def gh(folder, *args):
    # なぜ、変数がrなの？
    # subprocess..: ターミナルでコマンドを打つことと同じことをpythonからやる。
    # ["gh", *args]: 打つコマンド。
    r = subprocess.run(["gh", *args], cwd=folder, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh {' '.join(args)} が失敗しました:\n{r.stderr}")
    return r.stdout

# "ask_codex"関数の説明
# 指定したフォルダーとPRの差分を元にしたレビューをCodexに依頼する関数
def ask_codex(folder, diff):
    prompt = f"""次のPRの差分をレビューしてください。
- 本当に問題になるところだけを、大事な順に最大5つ
- 問題がなければ、findings は空でかまいません
- ファイルの変更はしないでください

--- 差分 ---
{diff[:30000]}
"""
    # Codexに繋ぐ
    with Codex() as codex:
        # 新しい会話を始める。
        # 今回だと、指定したフォルダーでの会話を始める。読み取り専用で
        thread = codex.thread_start(cwd=folder, sandbox=Sandbox.read_only)
        # 
        # メッセージを送り、答えを待つ
        # promptってなに？→ ask_codex関数の引数として渡されたPRの差分と指示文をまとめた文字列
        # promptは、PRの差分と指示文をまとめた文字列
        # output_schemaは、Codexに期待する出力の形式を指定するもの
        result = thread.run(prompt, output_schema=REVIEW_SCHEMA)

    if not result.final_response:
        sys.exit("Codexが答えを返さずに終わりました。もう一度ためしてください")

    # JSONの文字列をdictやリストに変換して返す。
    return json.loads(result.final_response)


def main():
    # 引数が足りないときは、使い方を出して止める
    if len(sys.argv) < 3:
        sys.exit("使い方: python review.py <フォルダ> <PR番号>\n例: python review.py . 2")

    # 絶対パスに変換する
    folder = str(Path(sys.argv[1]).expanduser().resolve())
    pr = sys.argv[2]  # PRの番号→これって#〇〇であっているのか？

    diff = gh(folder, "pr", "diff", pr)
    print("Codexがレビューしています…")
    review = ask_codex(folder, diff)

    lines = [f"**まとめ**：{review['summary']}", ""]
    for i, f in enumerate(review["findings"], 1):
        lines.append(f"{i}. [{LABEL[f['severity']]}] `{f['file']}` {f['line']}行目：{f['message']}")
        lines.append(f"   - 直し方：{f['suggestion']}")
    if not review["findings"]:
        lines.append("指摘はありません。")
    lines += ["", "---", "AIのレビューです。最後は人が見て決めます（pr-yoroshiku / review.py）"]
    comment = "\n".join(lines)
    print("\n" + comment + "\n")

    if input("このレビューをPRにコメントしていい？ (y/n) ").strip().lower() == "y":
        print(gh(folder, "pr", "comment", pr, "--body", comment).strip())
    else:
        print("コメントはしませんでした")


if __name__ == "__main__":
    main()

# なんで関数の中にある変数を外でも使えるのか？って点が意味わからないかな。
# 基本的に関数内で閉じるものを外で使う理由がわからないかな。
# pythonではOKなのかな？

# なんでスキーマはこの形なのかわからない。

# cwd:current working directoryの略。
# Codexに対してどのフォルダーで会話を始めるかを指定するもの。
# この書き方を知りたいかな→実験したいかな