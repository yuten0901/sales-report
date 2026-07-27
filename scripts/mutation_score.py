"""mutmut resultsの出力を集計し、ミューテーションスコアを算出する。

FIX2-01/FIX2-14(Codex#1/#5): 従来はこの集計ロジックを`.github/workflows/
mutation.yml`のヒアドキュメント内Pythonとして直接埋め込んでおり、pytestで
テストできない「未テストの本番ロジック」になっていた。QAポートフォリオと
してこれは弱い構造であるという指摘を受け、通常のモジュールへ切り出した。

また、`continue-on-error: true`のゲートと組み合わさることで「mutmut自体が
クラッシュ・0件収集」した場合でもワークフローが緑になってしまう
(=ミューテーションスコアが実質0%でもバッジが嘘をつく)問題があった。
`MutationCollectionError`により「収集失敗」を「真のスコア0%」と明確に
区別し、収集失敗時はCLIの終了コードを非ゼロにしてワークフロー自体を
失敗させる(スコアの良し悪しに関わらず、収集できたことは保証する)。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class MutationCollectionError(Exception):
    """ミューテーションが1件も収集されなかった場合(設定ミス・mutmutのクラッシュ等)。

    これは「スコア0%」とは異なる。0%は「収集はできたが1件も検知できなかった」
    という(それ自体は妥当な)結果だが、収集失敗はそもそも計測が成立していない。
    """


@dataclass(frozen=True, slots=True)
class MutationScoreResult:
    """算出したミューテーションスコアと、その内訳。"""

    counts: dict[str, int]
    total: int
    killed: int
    score: float


def parse_mutmut_results(text: str) -> Counter[str]:
    """`mutmut results`(`--all`有無いずれの出力形式でも)のテキストから、
    各行末尾の「: <status>」部分(killed/survived/timeout/suspicious等)を集計する。

    フォーマットに一致しない行(空行・ヘッダ等)は無視する。
    """
    counts: Counter[str] = Counter()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if ": " not in line:
            continue
        status = line.rsplit(": ", 1)[-1].strip()
        counts[status] += 1
    return counts


def compute_mutation_score(counts: Counter[str]) -> MutationScoreResult:
    """カウント結果からミューテーションスコアを算出する。

    FIX-12(前回)の教訓を踏襲し、killed/survivedだけでなくtimeout/suspicious/
    no tests/skipped等の全ステータスを分母に含める(一部を無視すると
    過大評価になる)。

    以下は「真のスコア」ではなく計測が成立していない状態として区別し、
    `MutationCollectionError`を送出する(FIX2-01/DEF-023):
    - 1件も収集できていない(total==0): 設定ミス・mutmutクラッシュ等。
    - 収集はされたが1件もkilled/survivedの実判定に到達していない
      (killed+survived==0): mutmutがベースライン(stats)収集で停止し、
      ミュータントを1個もテストせず全て`not checked`のまま終わったケース
      (CI初回実行で実際に発生・DEF-023)。これを見逃すと「スコア0%・緑」
      という無意味な結果が通ってしまう。なお「本物の0%」は survived>0
      (テストが実行されたが1個も殺せなかった)であり、これとは区別する。
    """
    total = sum(counts.values())
    if total == 0:
        msg = "ミューテーションが1件も収集されませんでした(設定を確認してください)"
        raise MutationCollectionError(msg)
    killed = counts.get("killed", 0)
    executed = killed + counts.get("survived", 0)
    if executed == 0:
        msg = (
            "ミュータントは収集されましたが、1件もkilled/survivedの実判定に到達しませんでした"
            f"(全て未実行の可能性・計測不成立)。内訳: {dict(counts)}"
        )
        raise MutationCollectionError(msg)
    score = killed / total * 100
    return MutationScoreResult(counts=dict(counts), total=total, killed=killed, score=score)


def main(argv: Sequence[str] | None = None) -> int:
    """CLIエントリポイント。

    `results_file`(`mutmut results`の出力を保存したテキストファイル)を読み、
    `score_file`にスコア(小数第1位までの文字列)を書き込む。

    戻り値: 0=正常にスコアを算出できた。1=収集失敗(ワークフローを赤にする
    ためcontinue-on-errorを付けずに呼び出すこと。FIX2-01/Codex#1対応)。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_file", type=Path, help="mutmut resultsの出力テキストファイル")
    parser.add_argument("score_file", type=Path, help="算出したスコアの書き込み先")
    args = parser.parse_args(argv)

    text = args.results_file.read_text(encoding="utf-8")
    counts = parse_mutmut_results(text)

    try:
        result = compute_mutation_score(counts)
    except MutationCollectionError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"ステータス内訳: {result.counts}")
    print(f"ミューテーションスコア: {result.score:.1f}% ({result.killed}/{result.total} killed)")
    args.score_file.write_text(f"{result.score:.1f}", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
