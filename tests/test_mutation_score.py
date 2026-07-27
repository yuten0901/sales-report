"""scripts/mutation_score.py のテスト。

FIX2-01/14(Codex#1/#5): 従来CIワークフローのヒアドキュメント内に直接
埋め込まれ、pytestでテストできなかった集計ロジックの回帰テスト。
docs/defects.md「FIX2-09/11/15」節・fix-spec-02参照。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from mutation_score import (
    MutationCollectionError,
    compute_mutation_score,
    main,
    parse_mutmut_results,
)

# --- parse_mutmut_results ----------------------------------------------------


def test_parse_mutmut_results_counts_statuses_from_all_all_format() -> None:
    """`mutmut results --all true`形式(killed/survived以外も列挙される)を解析できる。"""
    text = (
        "src/sales_report/models.py:10-11: killed\n"
        "src/sales_report/models.py:12-13: killed\n"
        "src/sales_report/loader.py:5-6: survived\n"
        "src/sales_report/report.py:1-2: timeout\n"
        "src/sales_report/report.py:3-4: suspicious\n"
    )
    counts = parse_mutmut_results(text)
    assert counts == Counter({"killed": 2, "survived": 1, "timeout": 1, "suspicious": 1})


def test_parse_mutmut_results_ignores_blank_and_non_matching_lines() -> None:
    """ヘッダ行・空行など「: 」を含まない行は無視する。"""
    text = "Legend for mutant statuses\n\nsrc/x.py:1-1: killed\n---\n"
    counts = parse_mutmut_results(text)
    assert counts == Counter({"killed": 1})


def test_parse_mutmut_results_empty_text_returns_empty_counter() -> None:
    assert parse_mutmut_results("") == Counter()


# --- compute_mutation_score ---------------------------------------------------


def test_compute_mutation_score_all_killed_is_100_percent() -> None:
    result = compute_mutation_score(Counter({"killed": 8}))
    assert result.score == pytest.approx(100.0)
    assert result.killed == 8
    assert result.total == 8


def test_compute_mutation_score_includes_non_killed_survived_statuses_in_denominator() -> None:
    """FIX-12の教訓の回帰確認: timeout/suspicious等もkilled/survivedと同様に
    分母に含める(一部ステータスを無視すると過大評価になる)。
    """
    counts = Counter({"killed": 6, "survived": 2, "timeout": 1, "suspicious": 1})
    result = compute_mutation_score(counts)
    assert result.total == 10
    assert result.score == pytest.approx(60.0)


def test_compute_mutation_score_zero_survived_is_100_percent() -> None:
    counts = Counter({"killed": 5, "survived": 0})
    result = compute_mutation_score(counts)
    assert result.score == pytest.approx(100.0)


def test_compute_mutation_score_no_killed_key_defaults_to_zero() -> None:
    """killedキー自体が存在しない(全滅)場合もKeyErrorにならずスコア0%になる。"""
    result = compute_mutation_score(Counter({"survived": 3}))
    assert result.score == pytest.approx(0.0)


def test_compute_mutation_score_zero_total_raises_collection_error() -> None:
    """FIX2-01(Codex#1): 1件も収集されなかった場合は「真のスコア0%」と区別し、
    MutationCollectionErrorを送出する(呼び出し側でワークフローを赤にするため)。
    """
    with pytest.raises(MutationCollectionError):
        compute_mutation_score(Counter())


# --- main (CLIエントリポイント) -----------------------------------------------


def test_main_writes_score_file_and_returns_zero_on_success(tmp_path: Path) -> None:
    results_file = tmp_path / "mutmut-results.txt"
    results_file.write_text(
        "src/x.py:1-1: killed\nsrc/x.py:2-2: killed\nsrc/x.py:3-3: survived\n",
        encoding="utf-8",
    )
    score_file = tmp_path / "mutmut-score.txt"

    exit_code = main([str(results_file), str(score_file)])

    assert exit_code == 0
    assert score_file.read_text(encoding="utf-8") == "66.7"


def test_main_returns_nonzero_and_does_not_write_score_file_when_collection_fails(
    tmp_path: Path,
) -> None:
    """FIX2-01(Codex#1): 収集失敗(1件も無い)場合は非ゼロを返し、
    継続不能な状態でスコアファイルを書かない(呼び出し側のワークフロー全体を
    赤にすることが目的であり、中途半端な成功を装わない)。
    """
    results_file = tmp_path / "mutmut-results.txt"
    results_file.write_text("", encoding="utf-8")
    score_file = tmp_path / "mutmut-score.txt"

    exit_code = main([str(results_file), str(score_file)])

    assert exit_code == 1
    assert not score_file.exists()
