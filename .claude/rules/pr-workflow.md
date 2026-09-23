# PRオープン後の運用ルール

このリポジトリでは、Issue化からPRのマージ・後片付けまでを、PRごとに指示されなくても一貫して進める（「いつものフロー」）。ac-adapter-rsの同名ルールとは違い、**個別のmerge指示は待たない**（下記3.）。

## 1. レビューsubagentの起動

- 独立した視点を得るため、fork（コンテキスト継承）ではなく新規general-purpose agentでレビューさせる
- レビューで見つかった指摘は確認の上で反映する。スコープ外の指摘はissue化する

## 2. 実機（macOS）での動作確認

- 独立したworktreeで動作確認する。fork（コンテキスト継承）ではなく新規general-purpose agentに依頼する
- 依頼する内容の定型:
  1. `git worktree add ~/worktrees/utavideo/<branch> <branch>` でPRのブランチ用worktreeを作る
  2. `CONTRIBUTING.md`の「確認」（`uv run ruff format && uv run ruff check && uv run pyright && uv run pytest`）を実行する
  3. PR本文が主張する挙動を実機で確認する
  4. 確認結果を `gh pr comment <番号> --body-file <ファイル>` で日本語で投稿する。OSユーザー名やホームディレクトリの絶対パスは書かない
  5. 不具合があれば、まず `gh issue list --state all` で重複がないか確認してから `gh issue create` で起票する。「PR #<番号> の動作確認中に見つかった」ことを明記する
  6. 確認が終わったら `git worktree remove ~/worktrees/utavideo/<branch>` と、使った一時ファイル（`/tmp`配下）を削除する
  7. 200〜300字程度で完了報告する（確認内容・問題の有無・issue化した場合は番号）

## 3. マージ

- CIが通り、レビュー指摘の反映と実機での動作確認が終わっていれば、**ユーザーからのPRごとの個別merge指示は待たずに**マージする
- `gh pr merge <番号> --merge --delete-branch=false` を使う（このリポジトリの実運用はmergeコミット方式。squashではない）
- マージ後、ローカルのworktreeとブランチを片付ける:
  ```sh
  git worktree remove ~/worktrees/utavideo/<branch>
  git branch -D <branch>
  ```
  worktreeがそのブランチをcheckoutしたままだと `git branch -D` が失敗するので、必ずworktree削除を先に行う

## 4. セッションの終了報告

委任された作業（Issue化・PR作成・レビュー・マージ・後片付け）がすべて終わり、そのセッションでやることがなくなったら、その旨と「このセッションは削除して構わない」旨を一言添えて報告する。
