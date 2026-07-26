# sales-report

複数の売上CSVを読み込み、店舗別・商品別・日別に集計してサマリレポート(CSV/Markdown)を出力するCLIツール。

[![CI](https://github.com/yuten0901/sales-report/actions/workflows/ci.yml/badge.svg)](https://github.com/yuten0901/sales-report/actions/workflows/ci.yml)
[![Mutation testing](https://github.com/yuten0901/sales-report/actions/workflows/mutation.yml/badge.svg)](https://github.com/yuten0901/sales-report/actions/workflows/mutation.yml)
[![Security](https://github.com/yuten0901/sales-report/actions/workflows/security.yml/badge.svg)](https://github.com/yuten0901/sales-report/actions/workflows/security.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

> カバレッジバッジは2026-07-26時点のローカル計測値(行/分岐ともに100%・手動更新)。最新の実測値はCIの`test-evidence-*` artifact(`coverage.xml`)で確認できる。
> ミューテーションスコアは`mutation.yml`の初回実行後に実測値を追記する。現状は公開前レビューで指摘された箇所を手動で個別検証(体系的な2回・各8件で全検知)しているが、**これは網羅的なmutmut実行の代替ではない**(経緯は[docs/test-report.md](docs/test-report.md) §3/§5参照)。

---

## これは何か

Excel等からエクスポートした売上CSV(複数ファイル・複数店舗)を集計し、店舗別・商品別・日別のサマリと、
スキップした行の理由付きエラーレポートを出力する。個人開発のポートフォリオとして、**アプリの機能そのものより
「どう品質を保証したか」を実物で示す**ことを目的に作成した。

```
$ sales-report --input data/sample/sales.csv --output out/summary.md
サマリレポートを出力しました: out\summary.md
```

```markdown
# 売上サマリレポート

## 店舗別

| 店舗 | 数量 | 金額 |
|---|---|---|
| 新宿店 | 4 | 104740 |
| 池袋店 | 11 | 109600 |
| 渋谷店 | 9 | 239100 |

## 合計

- 総数量: 24
- 総金額: 453440
```

---

## 品質へのアプローチ

1. **テスト設計書**([docs/test-design.md](docs/test-design.md))で同値分割・境界値分析・デシジョンテーブルから観点を導出
2. 導出した観点をIDで管理し、境界値・異常系を漏れなく網羅(観点ID → テスト関数の対応表あり)
3. **プロパティベーステスト**(Hypothesis)で「性質」を大量のランダム入力で検証
4. **ミューテーションテスト**でテスト自体が「バグを実際に検出できるか」を検証(mutmutはローカル未実行のため手動での個別検証で代替。網羅的な実測値はCI実行後に追記予定。詳細は[docs/test-report.md](docs/test-report.md))
5. CI(GitHub Actions)でOS×Pythonバージョンのマトリクステストと閾値ゲートを実行
6. **テスト実行結果(JUnit XML・カバレッジHTML)をCIのartifactとして自動保存** — 手作業のエビデンス収集を、CIの成果物として自動で残す形に置き換えた

「元QAとして、正常系だけでなく異常系・境界値まで責任を持つ」という進め方を、AIツールを活用しながら自分の設計・検証判断で実装したもの。

---

## インストール・Usage

```bash
pip install -e .
```

```bash
# 基本(Markdown出力)
sales-report --input data/sample/sales.csv --output out/summary.md

# CSV出力 + スキップ行の理由レポート
sales-report --input data/sample/sales_with_errors.csv --format csv \
  --output out/summary.csv --report-errors out/errors.csv

# ディレクトリ(複数CSV)をまとめて集計
sales-report --input data/sample/multi_store --output out/summary.md

# Slack通知(任意。既定では送信しない)
sales-report --input data/sample/sales.csv --slack-webhook https://hooks.slack.com/services/...
```

| オプション | 説明 | 既定値 |
|---|---|---|
| `--input`(必須) | CSVファイル、またはCSVを含むディレクトリのパス | - |
| `--format` | 出力形式: `csv` または `markdown` | `markdown` |
| `--output` | サマリレポートの出力先パス | `out/summary.md` |
| `--report-errors` | スキップした行の理由付きレポートの出力先(指定時のみ出力) | 出力しない |
| `--slack-webhook` | 指定時、サマリをSlackへ通知する | 送信しない |

終了コードは3段階(`docs/test-design.md` §1.4参照): `0`=成功 / `1`=有効な明細が0件 / `2`=入力・利用方法エラー。

`data/sample/`にデモ用CSV(正常データ・エラーを含むデータ・Shift-JISデータ・複数店舗ディレクトリ)を同梱している。

---

## テスト戦略

- **同値分割・境界値分析・デシジョンテーブル**で観点を導出([docs/test-design.md](docs/test-design.md))
- 数量0・単価0は有効(境界値)、負の値は無効、全角数字は明示的に拒否(実装中に発見・修正 → [docs/defects.md](docs/defects.md))
- **CSVインジェクション対策**(`=` `+` `-` `@`で始まる値の無害化)、**原子的書き込み**(プロセス中断時に中途半端な出力を残さない。fsync等の電源断レベルのdurabilityは対象外)、**冪等性**(同一入力での再実行結果がバイト同一)
- **プロパティベーステスト**(Hypothesis): 総合計が店舗別/商品別/日別集計の合計と必ず一致する、行の入力順序を変えても結果が不変、等
- **ゴールデンテスト**で出力フォーマットの回帰を検知
- **性能テスト**: 10万行を約1秒・メモリ約52MBで処理(実測値。テストは3秒/150MB以内を閾値として下限保証する。通常実行から分離、`pytest -m slow`で実行)

テストの実行方法:

```bash
pytest --cov --cov-report=term-missing   # 通常テスト(性能テストは除外)
pytest -m slow                            # 性能テストのみ
ruff check .                              # lint
mypy src/ tests/                          # 型チェック(テストコード自体もstrict対象)
mutmut run                                # ミューテーションテスト(要WSL。Windowsネイティブ非対応)
```

## QAプロセス成果物

顧客に納品する成果物と同じ意識で、実装だけでなくQAプロセス自体もドキュメント化している。

| 文書 | 内容 |
|---|---|
| [docs/test-design.md](docs/test-design.md) | テスト設計書(同値分割・境界値・デシジョンテーブル・観点ID対応表・リスクベース優先度) |
| [docs/test-report.md](docs/test-report.md) | テスト完了報告書(実施結果・残存リスク・リリース可否判断) |
| [docs/defects.md](docs/defects.md) | 不具合管理表(実装中に実際に検出した不具合のみ。架空の事例は記載しない) |
| [docs/exploratory-notes.md](docs/exploratory-notes.md) | 探索的テストの記録(チャーターとセッションノート) |

CIの実行結果(JUnit XML・カバレッジHTMLレポート)は各ワークフローのartifactとして自動保存され、mainブランチへのpush時にはカバレッジHTMLレポートをGitHub Pagesへ公開する。

---

## 設計メモ

- **金額計算は`Decimal`のみで行う**(floatを一切使わない)。丸め誤差を出さないための設計上の制約。ただしDecimalも既定精度(28桁)を超えると丸め誤差が生じるため、`unit_price`(整数部12桁・小数部2桁まで)・`quantity`(9桁まで)に入力段階で上限を設け、集計処理自体も精度50桁で実行している([docs/defects.md](docs/defects.md) DEF-010)
- **数量0・単価0は有効な境界値**(無料サンプル等の実業務ケースを想定)。負の値のみ無効
- **重複明細はエラーにせず合算**する(同一日・店舗・商品の複数行を許容)
- **1ファイルの文字コード事故で全体を止めない**(UTF-8→Shift-JISへのフォールバック、それでも失敗したファイルのみスキップして処理継続)
- **CSVインジェクション対策**として、`=` `+` `-` `@`で始まる文字列の先頭に`'`を付与(OWASP推奨)
- **CLI終了コードは3段階**とし、「有効な明細が0件なのに正常終了する」という黙った失敗を作らない

## 開発

```bash
pip install -e ".[dev]"
pytest --cov
ruff check .
mypy src/ tests/
```

Python 3.11以上。依存関係は`pyproject.toml`参照。

## ライセンス

MIT
