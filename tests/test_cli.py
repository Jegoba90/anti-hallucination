"""python -m antihallucination: the method without writing Python.

Exit codes are part of the contract, because a script or a CI job acts on
them: 0 every sentence passed, 1 some failed, 2 the input could not be read,
3 the writer failed.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import cli
from antihallucination.data import DataError, load_data, parse_data
from antihallucination.errors import WriterError

_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sales"
DATA = str(_EXAMPLE / "data.json")


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


class TestVerify:
    def test_the_ai_text_fails_and_pythons_sentences_go_out(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out, _ = _run(capsys, "verify", str(_EXAMPLE / "written_by_an_ai.txt"), "--data", DATA)

        assert code == 1
        assert "unbacked_number: «5 %»" in out
        assert "→ Las ventas fueron 1.250 unidades (-3,2 %)." in out
        assert "Las ventas fueron 1.250 unidades (-3,2 %). Se sumaron 48 clientes nuevos." in out

    def test_a_clean_text_exits_zero(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        text = tmp_path / "ok.txt"
        text.write_text("Las ventas cayeron 3,2 % hasta 1.250 unidades.", encoding="utf-8")

        code, out, _ = _run(capsys, "verify", str(text), "--data", DATA)

        assert code == 0
        assert "✓ kept" in out

    def test_standard_input_is_read_with_a_dash(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io

        monkeypatch.setattr(sys, "stdin", io.StringIO("Se sumaron 48 clientes."))

        assert _run(capsys, "verify", "-", "--data", DATA)[0] == 0

    def test_json_output_carries_the_receipt(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out, _ = _run(capsys, "verify", str(_EXAMPLE / "written_by_an_ai.txt"), "--data", DATA, "--json")
        result = json.loads(out)

        assert code == 1
        assert result["ok"] is False
        assert result["receipt"]["digest"].startswith("sha256:")
        assert [d["action"] for d in result["decisions"]] == ["replaced", "replaced", "kept"]


class TestComposeAndReceipt:
    def test_a_saved_receipt_verifies_and_replays(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        receipt = tmp_path / "receipt.json"
        code, out, _ = _run(capsys, "compose", str(_EXAMPLE / "draft.txt"), "--data", DATA, "--receipt", str(receipt))

        assert code == 1  # the forecast sentence was dropped
        assert "una caída leve" in out
        code, out, _ = _run(capsys, "receipt", str(receipt), "--data", DATA)
        assert code == 0
        assert "Digest: verified" in out and "Replay: reproduced" in out

    def test_a_tampered_receipt_fails(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        receipt = tmp_path / "receipt.json"
        _run(capsys, "compose", str(_EXAMPLE / "draft.txt"), "--data", DATA, "--receipt", str(receipt))
        data = json.loads(receipt.read_text(encoding="utf-8"))
        data["text"] = "Todo subió."
        receipt.write_text(json.dumps(data), encoding="utf-8")

        code, out, _ = _run(capsys, "receipt", str(receipt))

        assert code == 1
        assert "Digest: mismatch" in out

    def test_compose_needs_one_language(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        data = tmp_path / "auto.json"
        data.write_text(json.dumps({"locale": "auto", "facts": [{"name": "a", "value": 1}]}), encoding="utf-8")
        draft = tmp_path / "d.txt"
        draft.write_text("Fue {a}.", encoding="utf-8")

        code, _, err = _run(capsys, "compose", str(draft), "--data", str(data))

        assert code == 2
        assert "--locale es or --locale en" in err


class TestWrite:
    def test_a_model_drafts_and_the_checks_decide(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake(system: str, prompt: str) -> str:
            assert "1.250" not in prompt and "-3,2" not in prompt
            return "En el {periodo}, las ventas cayeron {variacion_ventas:abs} hasta {ventas}."

        monkeypatch.setattr(cli, "make_writer", lambda args: fake)

        code, out, _ = _run(capsys, "write", "--data", DATA, "--brief", "Resumen corto.")

        assert code == 0
        assert "En el tercer trimestre de 2026, las ventas cayeron 3,2 % hasta 1.250 unidades." in out

    def test_a_writer_failure_exits_three(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def down(system: str, prompt: str) -> str:
            raise WriterError("no key")

        monkeypatch.setattr(cli, "make_writer", lambda args: down)

        code, _, err = _run(capsys, "write", "--data", DATA, "--brief", "x")

        assert code == 3
        assert "the writer failed: no key" in err

    def test_a_compatible_writer_needs_a_model(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, _, err = _run(capsys, "write", "--data", DATA, "--brief", "x", "--writer", "ollama")

        assert code == 2
        assert "needs --model" in err


class TestDataFile:
    def test_the_example_reads_and_a_rule_decides_its_label(self) -> None:
        data = load_data(DATA)

        assert [fact.name for fact in data.facts][:2] == ["ventas", "variacion_ventas"]
        assert data.labels[1].text == "caída leve"
        assert data.labels[1].rule == "-5 ≤ -3.2 < -1"
        assert str(data.facts[1].number) == "-3.2"

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            ({"facts": [{"name": "a", "value": "1"}]}, r"facts\[0\].value must be a number"),
            ({"facts": [{"name": "a", "value": 1, "colour": "red"}]}, "unknown keys: colour"),
            ({"labels": [{"name": "t", "from": "nada", "thresholds": [], "otherwise": "x"}]}, "names no fact"),
            ({"checks": {"spelling": False}}, "checks may only switch"),
            ({"locale": "fr"}, "locale must be"),
            ({"facts": [{"name": "a b", "value": 1}]}, "identifier"),
            ({"extra": 1}, "unknown keys: extra"),
        ],
    )
    def test_a_wrong_file_says_where(self, raw: dict[str, object], message: str) -> None:
        with pytest.raises(DataError, match=message):
            parse_data(raw)

    def test_a_broken_file_exits_two(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")

        code, _, err = _run(capsys, "verify", "-", "--data", str(bad))

        assert code == 2
        assert "not valid JSON" in err
