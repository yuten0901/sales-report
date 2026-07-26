# テスト設計書（sales-report）

作成: 2026-07-26 / このツールの品質保証のためのテスト設計。**実装前に観点を導出し、実装は各観点IDに対応するテスト関数を作る**（トレーサビリティを確保する）。

## 1. 対象と仕様の確定

テスト設計に入る前に、あいまいだった業務ルールを明文化する（これ自体がQA作業の一部＝要件の穴を先に潰す）。

### 1.1 入力仕様（CSV1行 = 1明細）

| フィールド | 型 | ルール |
|---|---|---|
| `date` | 日付文字列 | `YYYY-MM-DD` 形式のみ有効 |
| `store` | 文字列 | 前後空白を除去して非空であること |
| `product` | 文字列 | 前後空白を除去して非空であること |
| `quantity` | 整数 | **ASCII半角数字のみ**を10進整数として解釈、**0以上**（0は有効＝境界値、負は無効）、**桁数9桁まで（10億未満）** |
| `unit_price` | 10進数（Decimal） | **ASCII半角数字のみ**を数値として解釈、**0以上**（0は有効＝境界値、負は無効）、**整数部12桁まで・小数部2桁まで（銭単位）** |

> **金額仕様の追加（2026-07-26・FIX-04/DEF-010）**: 既定のDecimalコンテキストは精度28桁しかなく、桁数を無制限にすると、大桁の値や大量行の合算で**例外なく丸め誤差が発生する**（Codexレビューが単価29桁×数量9の掛け算で実測: 得られた値と正しい値が9円ずれた）。業務データとして現実的な範囲（quantity 9桁・unit_price 整数部12桁+小数部2桁）に入力段階で制限し、超過は行エラーとする。あわせて`aggregate()`は`decimal.localcontext(prec=50)`で実行し、上限値を大量合算しても丸めが起きない余裕を持たせる（実測: 上限値ぎりぎりの明細を100,001件合算すると既定精度28桁では丸め誤差が発生し、50桁では発生しないことを確認済み）。

> ⚠️ **実装前の仕様確認で発見した非自明な挙動**: Python標準の `int()` / `decimal.Decimal()` は**全角数字を暗黙に受理する**（例: `int('５') == 5`）。対策しないと「全角数字は無効」という意図（EQ-QTY-02, EQ-PRICE-02）に反し、意図せず緩いバリデーションになる。→ **ASCII半角のみを許可する明示チェックを追加**する（`docs/defects.md` に記録）。

- **金額** = `quantity * unit_price`（`Decimal`で計算し丸め誤差を出さない）。
- **重複明細**（同一date/store/productの複数行）: エラーとせず**そのまま合算**する（既定方針）。
- **行の検証失敗**: いずれか1フィールドでも無効なら**行全体を無効**とし、**その行で検出した全ての理由**（複数フィールドが同時に不正な場合も全部）を記録する（1回のエラーレポートで複数の問題を直せるように＝QA的な配慮）。

### 1.2 ファイル・エンコーディング仕様

- 対応エンコーディング: **UTF-8（BOM有無問わず） → 失敗時は Shift-JIS(cp932) にフォールバック**。両方失敗した場合、そのファイルを**ファイルレベルのエラー**としてスキップし処理を継続する（1ファイルの文字コード事故で全体を止めない）。
- **空ファイル（0バイト）** と **ヘッダ行のみ（データ0行）** は、いずれも「有効な明細が無い」の一種として扱う（§1.4のexit code参照）。

### 1.3 出力仕様

- `--format csv|markdown`（既定 markdown）。
- `--report-errors <path>` 指定時のみ、スキップした行の理由付きレポートを出力。
- **CSVインジェクション対策**: CSV出力時、フィールド値が `=` `+` `-` `@` またはタブ/CRで始まる場合、先頭に `'` を付与して無害化する（Excel等での数式実行を防ぐ・OWASP推奨）。数値列（金額・数量）には適用しない。
- **Markdownテーブルのエスケープ**: セル内の `|` と改行をエスケープし、テーブル崩れを防ぐ（セキュリティでなく表示崩れ対策）。
- **原子的書き込み**: 一時ファイルに書き込んでから `os.replace()` で本番パスに置換する。処理中断時に壊れた/中途半端な出力ファイルを残さない。
- **冪等性**: 同一入力・同一オプションで複数回実行しても、出力内容はバイト同一（集計順序をソートして固定する）。
- **入力・出力パスの衝突禁止（FIX-03/DEF-009・2026-07-26追加）**: 以下のいずれかに該当する場合、処理を開始せずexit 2（入力・利用方法エラー）とする。
  - `--input`が指すファイル、または`--input`が指すディレクトリの中に`--output`が位置する。
  - `--input`が指すファイル、または`--input`が指すディレクトリの中に`--report-errors`が位置する。
  - `--output`と`--report-errors`が同一パス。
  - 背景: 衝突を許すと、元の入力データが集計結果やエラーレポートで**正常終了(exit 0)のまま上書きされ、気づかれずに消える**（探索的テストで「クラッシュしないから安全」と誤判定した実例あり。`docs/exploratory-notes.md`セッション3参照）。パス比較は`resolve()`で正規化してから行う。

### 1.4 CLI終了コード（3段階）

| exit code | 意味 | 具体例 |
|---|---|---|
| `0` | 成功 | 1件以上の有効な明細があり、レポートを生成できた（一部行がスキップされていても可） |
| `1` | 処理対象データなし | 全入力ファイルを通じて有効な明細が0件（空ファイルのみ／ヘッダのみ／全行が検証エラー） |
| `2` | 入力・利用方法エラー | 入力パスが存在しない／ディレクトリ内にCSVファイルが1つもない／出力先に書き込めない／不正なCLIオプション値 |

「黙って0件成功にしない」（正常終了だが中身が空、を作らない）ための設計。

### 1.5 通知（Slack, optional）

- `--slack-webhook <url>` 指定時のみPOST。既定は送信しない。
- 送信失敗（HTTPエラー・タイムアウト）はCLI全体の失敗にはしない（レポート生成は成功として扱い、通知失敗のみ警告表示）— レポート生成という主目的を通知の可用性に依存させないため。

---

## 2. 同値分割（Equivalence Partitioning）

各フィールドの入力を有効/無効クラスに分割する。ID接頭辞 `EQ-`。

| ID | フィールド | クラス | 例 | 有効/無効 |
|---|---|---|---|---|
| EQ-DATE-01 | date | 正しいISO日付 | `2026-07-26` | 有効 |
| EQ-DATE-02 | date | 不正フォーマット | `2026/07/26`, `26-07-2026` | 無効 |
| EQ-DATE-03 | date | 空文字 | `` | 無効 |
| EQ-DATE-04 | date | 存在しない日付 | `2026-02-30` | 無効 |
| EQ-STORE-01 | store | 非空文字列 | `渋谷店` | 有効 |
| EQ-STORE-02 | store | 空文字/空白のみ | ``, `   ` | 無効 |
| EQ-PRODUCT-01 | product | 非空文字列 | `商品A` | 有効 |
| EQ-PRODUCT-02 | product | 空文字/空白のみ | ``, `   ` | 無効 |
| EQ-QTY-01 | quantity | 正の整数 | `5` | 有効 |
| EQ-QTY-02 | quantity | 非数値文字列（全角数字含む） | `abc`, `５`(全角) | 無効 |
| EQ-QTY-03 | quantity | 小数 | `1.5` | 無効（整数でない） |
| EQ-QTY-04 | quantity | 空文字 | `` | 無効 |
| EQ-PRICE-01 | unit_price | 正の小数/整数 | `1200`, `1200.50` | 有効 |
| EQ-PRICE-02 | unit_price | 非数値文字列 | `abc`, `¥1200` | 無効 |
| EQ-PRICE-03 | unit_price | 空文字 | `` | 無効 |

## 3. 境界値分析（Boundary Value Analysis）

ID接頭辞 `BV-`。

| ID | 対象 | 境界 | 期待 |
|---|---|---|---|
| BV-QTY-01 | quantity | `0` | **有効**（金額0円として集計） |
| BV-QTY-02 | quantity | `-1`（0未満） | 無効 |
| BV-QTY-03 | quantity | 大きい整数（例 `1000000`） | 有効・オーバーフローしない |
| BV-QTY-04 | quantity | 桁数9桁（`999999999`）/ 10桁（`1000000000`） | 9桁＝有効境界、10桁＝無効（FIX-04/DEF-010: 桁数上限） |
| BV-PRICE-01 | unit_price | `0` | **有効**（金額0円として集計） |
| BV-PRICE-02 | unit_price | `-0.01`（0未満） | 無効 |
| BV-PRICE-03 | unit_price | 小数点以下がある値（例 `100.99`） | Decimalで正確に計算・丸め誤差なし |
| BV-PRICE-04 | unit_price | 整数部12桁（有効）/13桁（無効）、小数部2桁（有効）/3桁（無効） | FIX-04/DEF-010: 桁数上限（既定Decimalコンテキストの精度28桁による丸め誤差を防ぐ） |
| BV-FILE-01 | ファイル | 0バイト（空ファイル） | 有効行0件 → exit 1 |
| BV-FILE-02 | ファイル | ヘッダ行のみ（データ0行） | 有効行0件 → exit 1 |
| BV-FILE-03 | ファイル | データ1行のみ | 正しく単一集計 |
| BV-FILE-04 | ファイル | 大量行（10万行） | 正常完了・メモリ線形（性能テスト） |
| BV-ENC-01 | エンコーディング | UTF-8（BOM無し） | 正しく読める |
| BV-ENC-02 | エンコーディング | UTF-8（BOM有り） | 正しく読める |
| BV-ENC-03 | エンコーディング | Shift-JIS | 正しく読める |
| BV-ENC-04 | エンコーディング | 上記いずれでもデコード不可 | 該当ファイルをスキップしファイルレベルエラー記録・処理継続 |
| BV-ENC-05 | ファイル読込 | 読込時のOSError（権限エラー・読込中のファイル消失等） | 該当ファイルをスキップしファイルレベルエラー記録・処理継続（FIX-06/DEF-012。当初`UnicodeDecodeError`のみ捕捉しておりOSErrorは未捕捉で全体停止していた） |
| BV-DUP-01 | 明細 | 同一date/store/productが複数行 | エラーにせず合算 |
| BV-SEC-01 | 出力文字列 | `=cmd`, `+1+1`, `-1`, `@SUM(A1)` で始まる値 | CSV出力時 `'` を先頭付与し無害化 |
| BV-SEC-02 | 出力文字列 | 通常の文字列（上記記号で始まらない） | 無害化されず、そのまま出力 |

## 4. デシジョンテーブル（Decision Table）

ID接頭辞 `DT-`。

### DT-1: 行の検証（各フィールドの有効性の組み合わせ → 行の扱い）

| ケース | date | store | product | quantity | unit_price | 結果 |
|---|---|---|---|---|---|---|
| DT-1-01 | 有効 | 有効 | 有効 | 有効 | 有効 | 行を採用・集計に加算 |
| DT-1-02 | **無効** | 有効 | 有効 | 有効 | 有効 | 行をスキップ・理由="date不正" |
| DT-1-03 | 有効 | **無効** | 有効 | 有効 | 有効 | 行をスキップ・理由="store空" |
| DT-1-04 | 有効 | 有効 | 有効 | **無効** | 有効 | 行をスキップ・理由="quantity不正" |
| DT-1-05 | 有効 | 有効 | 有効 | 有効 | **無効** | 行をスキップ・理由="unit_price不正" |
| DT-1-06 | **無効** | 有効 | 有効 | **無効** | 有効 | 行をスキップ・理由に**両方**含む（複合不正） |
| DT-1-07 | **無効** | **無効** | **無効** | **無効** | **無効** | 行をスキップ・理由に**全項目**含む |

> **観点の軸を追加（2026-07-26・FIX-01/DEF-006）**: 上表は「各フィールドが有効/無効」の組み合わせのみを網羅しており、**「フィールドがそもそも存在しない」**という軸が抜けていた。実装前提（CSVの列数がヘッダと一致する）が崩れた場合の観点を追加する。

| ケース | 内容 | 結果 |
|---|---|---|
| DT-1-08 | **列数不足**（ヘッダ5列に対しデータ行が3列等） | 不足した列は空文字として扱われ、当該フィールドが無効（例: quantityが空）として行エラーになる。**クラッシュしない**（修正前は`None.strip()`でAttributeError） |
| DT-1-09 | **列数過剰**（ヘッダより多い値がある行） | 余分な値は無視され、必須列が揃っていれば正常に処理される（`csv.DictReader`の`restkey`既定動作） |

### DT-2: ファイル/実行結果 → CLI終了コード

| ケース | 入力パス存在 | CSVファイル発見 | 有効行数 | 終了コード |
|---|---|---|---|---|
| DT-2-01 | 存在しない | - | - | `2` |
| DT-2-02 | 存在する(ディレクトリ) | 0件 | - | `2` |
| DT-2-03 | 存在する | 発見 | 0件(空/ヘッダのみ/全行無効) | `1` |
| DT-2-04 | 存在する | 発見 | 1件以上（一部無効行あり） | `0`（かつ`--report-errors`指定時はエラーレポート出力） |
| DT-2-05 | 存在する | 発見 | 全行有効 | `0` |
| DT-2-06 | 存在する | 発見 | 1件以上（出力先に書込不可） | `2`（FIX-02/DEF-008: 修正前は生のOSErrorが伝播しexit `1`になっていた。`1`は「有効明細0件」の意味と衝突しcronでの誤認を招くため`2`に統一） |
| DT-2-07 | 存在する | 発見 | 1件以上（入出力パスが衝突） | `2`（FIX-03/DEF-009: `--output`/`--report-errors`が`--input`と衝突する場合。修正前は正常終了(exit0)のまま元データを破壊していた） |

### DT-3: 出力オプションの組み合わせ

| ケース | `--format` | `--report-errors` | スキップ行 | 結果 |
|---|---|---|---|---|
| DT-3-01 | markdown | 未指定 | あり | サマリのみ出力（エラー詳細は出さない） |
| DT-3-02 | csv | 指定 | あり | サマリ＋エラーレポート両方出力 |
| DT-3-03 | csv | 指定 | なし | サマリのみ（エラーレポートは0件でも空ファイルを作る or 作らない→**空ファイルは作らない**方針とし、その旨をREADMEに明記） |
| DT-3-04 | 不正な値(例 `xml`) | - | - | exit `2`（CLIバリデーションエラー） |

---

## 5. 観点ID → テスト関数 対応表（トレーサビリティ）

実装完了時点（2026-07-26）の実際のテスト関数名で確定させた表。**parametrizeのテストIDに観点IDをそのまま埋め込んでいる**ため、`pytest -k "EQ-QTY"` のように観点IDでテストを絞り込める（表と実装の乖離が起きにくい設計）。

| 観点ID | テストファイル | テスト関数名（parametrize IDに観点IDを埋め込み） |
|---|---|---|
| EQ-DATE-01〜04 | `tests/test_models.py` | `test_validate_date_valid[EQ-DATE-01*]`, `test_validate_date_invalid[EQ-DATE-02*/03*/04*]` |
| EQ-STORE-01〜02, EQ-PRODUCT-01〜02 | `tests/test_models.py` | `test_validate_text_field_valid[EQ-STORE-01*]`, `test_validate_text_field_invalid[EQ-STORE-02*]`（store/productは同一実装を共有） |
| EQ-QTY-01〜04 | `tests/test_models.py` | `test_validate_quantity_valid[EQ-QTY-01*]`, `test_validate_quantity_invalid[EQ-QTY-02*/03*/04*]`, `test_validate_quantity_rejects_fullwidth_explicitly` |
| EQ-PRICE-01〜03 | `tests/test_models.py` | `test_validate_unit_price_valid[EQ-PRICE-01*]`, `test_validate_unit_price_invalid[EQ-PRICE-02*/03*]` |
| BV-QTY-01〜03 | `tests/test_models.py`, `tests/test_aggregate.py` | `test_validate_quantity_valid[BV-QTY-01-zero/BV-QTY-03-large]`, `test_validate_quantity_invalid[BV-QTY-02*]`, `test_sale_row_amount_zero_quantity_is_zero_yen`, `test_aggregate_boundary_zero_quantity_and_zero_price` |
| BV-QTY-04 | `tests/test_models.py` | `test_validate_quantity_valid[BV-QTY-04-max-digits-ok]`, `test_validate_quantity_invalid[BV-QTY-04-exceeds-max-digits]` |
| BV-PRICE-01〜03 | `tests/test_models.py`, `tests/test_aggregate.py` | `test_validate_unit_price_valid[BV-PRICE-01-zero/BV-PRICE-03-precise]`, `test_validate_unit_price_invalid[BV-PRICE-02*]`, `test_sale_row_amount_no_rounding_error_on_repeated_addition`, `test_aggregate_precise_decimal_no_rounding_error` |
| BV-PRICE-04 | `tests/test_models.py`, `tests/test_aggregate.py` | `test_validate_unit_price_valid[BV-PRICE-04-max-integer-digits-ok]`, `test_validate_unit_price_invalid[BV-PRICE-04-exceeds-*]`, `test_aggregate_no_rounding_at_large_scale_with_default_28_digit_precision_would_fail` |
| BV-FILE-01 | `tests/test_loader.py` | `test_load_file_empty_file_is_file_error` |
| BV-FILE-02 | `tests/test_loader.py`, `tests/test_cli.py` | `test_load_file_header_only_returns_empty_without_file_error`, `test_dt2_03_zero_valid_rows_exits_no_data` |
| BV-FILE-03 | `tests/test_loader.py`, `tests/test_cli.py` | `test_load_file_single_row`, `test_bv_file_03_single_row_succeeds` |
| BV-FILE-04 | `tests/test_performance.py` | `test_large_input_performance_completes_within_time_budget`, `test_large_input_memory_stays_bounded`（marker=slow・既定除外） |
| BV-ENC-01 | `tests/test_loader.py` | `test_load_file_utf8_without_bom` |
| BV-ENC-02 | `tests/test_loader.py` | `test_load_file_utf8_with_bom` |
| BV-ENC-03 | `tests/test_loader.py` | `test_load_file_shift_jis` |
| BV-ENC-04 | `tests/test_loader.py` | `test_load_file_undecodable_bytes_becomes_file_error`, `test_load_files_one_broken_file_does_not_stop_others` |
| BV-ENC-05 | `tests/test_loader.py` | `test_load_file_permission_error_becomes_file_error_not_crash`, `test_load_files_permission_error_on_one_file_does_not_stop_others` |
| BV-DUP-01 | `tests/test_aggregate.py` | `test_aggregate_duplicate_lines_are_summed` |
| BV-SEC-01 | `tests/test_report.py` | `test_sanitize_csv_field_neutralizes_dangerous_prefixes[BV-SEC-01-*]`, `test_render_csv_report_sanitizes_dangerous_store_name`, `test_render_errors_csv_sanitizes_file_path_column`（FIX-07/DEF-007: パス列も無害化されることの検証） |
| BV-SEC-02 | `tests/test_report.py` | `test_sanitize_csv_field_leaves_normal_values_untouched[BV-SEC-02-*]` |
| DT-1-01〜07 | `tests/test_models.py` | `test_parse_row_dt1_01_all_valid` 〜 `test_parse_row_dt1_07_all_fields_invalid`（7関数） |
| DT-1-08 | `tests/test_loader.py`, `tests/test_models.py` | `test_load_file_short_row_is_recorded_as_error_not_crash`, `test_parse_row_handles_none_values_without_crashing` |
| DT-1-09 | `tests/test_loader.py` | `test_load_file_excess_columns_are_ignored_safely` |
| DT-2-01〜05 | `tests/test_cli.py` | `test_dt2_01_nonexistent_input_path_exits_usage_error` 〜 `test_dt2_05_all_valid_rows_exits_success`（5関数） |
| DT-2-06 | `tests/test_cli.py` | `test_dt2_06_output_write_failure_exits_usage_error_not_no_data`, `test_dt2_06_report_errors_write_failure_exits_usage_error` |
| DT-2-07 | `tests/test_cli.py` | `test_fix03_input_file_equals_output_is_rejected_and_data_preserved`, `test_fix03_output_inside_input_directory_is_rejected`, `test_fix03_output_equals_report_errors_is_rejected`, `test_fix03_report_errors_equals_input_file_is_rejected`, `test_fix03_report_errors_inside_input_directory_is_rejected`, `test_fix03_directory_input_with_non_colliding_report_errors_succeeds`, `test_fix03_normal_separate_paths_still_succeed`（誤検知なしの確認） |
| （ファイルレベル警告の表示） | `tests/test_cli.py` | `test_cli_warns_about_file_level_error_but_still_succeeds`（旧・冪等性テストが偶然カバーしていた経路を意図的なテストに置き換えたもの。DEF-009修正時に発見） |
| DT-3-01〜04 | `tests/test_cli.py` | `test_dt3_01_markdown_without_report_errors_skips_error_file` 〜 `test_dt3_04_invalid_format_exits_usage_error`（4関数） |
| （性質検証・6性質） | `tests/test_properties.py` | `test_property_total_amount_equals_sum_of_{store,product,date}_amounts`, `test_property_total_quantity_equals_sum_of_store_quantities`, `test_property_aggregate_is_order_independent`, `test_property_no_negative_amounts_when_inputs_nonnegative` |
| （出力回帰） | `tests/test_golden.py` | `test_golden_csv_report_matches_reference`, `test_golden_markdown_report_matches_reference` |
| （堅牢性: 原子的書き込み・冪等性） | `tests/test_robustness.py` | `test_atomic_write_interruption_leaves_previous_content_intact`, `test_atomic_write_interruption_when_no_previous_file_leaves_nothing`, `test_idempotent_reruns_produce_byte_identical_output`, `test_idempotent_reruns_with_directory_input_and_multiple_files` |
| （通知） | `tests/test_notify.py` | `test_build_slack_payload_contains_totals`, `test_send_slack_summary_success_posts_expected_payload`, `test_send_slack_summary_raises_notify_error_on_{http_error,connection_failure}` |
| （構造化ログ） | `tests/test_logging_setup.py`, `tests/test_cli.py` | `test_build_run_summary_fields`, `test_log_run_summary_*`, `test_structured_log_summary_emitted_on_{success,no_data}` |

> 注記: `tests/test_security.py` / `tests/test_robustness.py` の分割方針は実装時に見直した。CSVインジェクション対策(BV-SEC-*)は`report.py`の責務であるため`tests/test_report.py`に統合し、独立した`test_security.py`は作成していない。

---

## 6. リスクベースの優先度（何を厚く・何を薄くテストするか）

| 領域 | 優先度 | 理由 |
|---|---|---|
| 金額計算（Decimal） | **最優先** | 金額誤りは業務システムで最も致命的。丸め誤差はDecimal選定の根拠そのもの |
| 文字コード判定 | **最優先** | 日本語業務データで実際に頻発する事故（Shift-JIS混在） |
| 行の検証ロジック | 高 | データ品質の入口。ここが緩いと下流の集計が全部信用できなくなる |
| CSVインジェクション対策 | 高 | 実在するセキュリティリスク。対策漏れは実害につながる |
| CLI終了コード | 中 | 自動化（cron等）で他ツールと連携する際の契約 |
| 出力フォーマット（markdown/csv） | 中 | 表示崩れは業務影響が限定的だが信頼感を損なう |
| Slack通知 | 低 | 主機能（レポート生成）の付加機能。失敗しても主機能は守る設計にしている |
| 性能（10万行） | 低〜中 | 想定利用規模では通常発生しないが、将来の拡張に備え下限保証はしておく |

この優先度は `docs/test-report.md` の実施結果・残存リスクの記述と対応させる。
