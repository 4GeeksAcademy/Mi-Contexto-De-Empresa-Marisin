"""Conversión, metadatos y métricas de legibilidad del flujo RFP (Hito 9 · Parte 1)."""

from datetime import date

import pytest

from data.pipelines.rfp_intake import convert, metrics
from data.pipelines.rfp_intake import metadata as metadata_agent
from rfp_helpers import FORMAL, INFORMAL, INVALID, ScriptedLLM, load, offline_llm


# --------------------------------------------------------------------------- #
# Conversión PDF → Markdown
# --------------------------------------------------------------------------- #
def test_clean_markdown_turns_pdfminer_bullets_into_markdown_bullets():
    raw = "2. Scope\r\n\r\n(cid:127) Almacenamiento   \n(cid:127) Devoluciones\n\n\n\nFin\x0c"

    assert convert.clean_markdown(raw) == "2. Scope\n\n- Almacenamiento\n- Devoluciones\n\nFin\n"


def test_only_real_pdfs_are_accepted():
    assert convert.looks_like_pdf(b"%PDF-1.7\n...")
    assert not convert.looks_like_pdf(b"PK\x03\x04 docx")
    assert not convert.looks_like_pdf(b"")


def test_a_missing_pdf_is_a_conversion_error(tmp_path):
    pytest.importorskip("markitdown")
    with pytest.raises(convert.ConversionError):
        convert.pdf_to_markdown(tmp_path / "no-existe.pdf")


# --------------------------------------------------------------------------- #
# Metadatos (reglas)
# --------------------------------------------------------------------------- #
def test_formal_rfp_metadata_modaviva_spain_eur_without_lastmile():
    extracted = metadata_agent.rules_metadata(load(FORMAL))

    assert extracted.client_name == "ModaViva"
    assert extracted.client_country == "Spain"
    assert extracted.currency == "EUR"
    assert extracted.services_requested == ["warehousing", "reverse_logistics"]
    assert extracted.departments_needed == ["warehouse", "reverse"]
    assert extracted.monthly_volume is None  # 15.000 SKUs no es un volumen mensual
    assert extracted.deadline == date(2026, 8, 28)
    assert extracted.contact.name == "Elena Bosch"


def test_informal_rfp_metadata_luna_us_usd_with_volume():
    extracted = metadata_agent.rules_metadata(load(INFORMAL))

    assert extracted.client_name == "Luna Cosmetics"
    assert extracted.client_country == "United States"
    assert extracted.currency == "USD"
    assert extracted.services_requested == ["warehousing", "last_mile"]
    assert extracted.departments_needed == ["warehouse", "lastmile"]
    assert extracted.monthly_volume == 5000
    assert extracted.deadline is None  # «around August 24th» no trae año
    assert "August 24th" in extracted.deadline_text
    assert extracted.contact.name == "Maya Chen"


# --------------------------------------------------------------------------- #
# Metadatos (LLM + guardas)
# --------------------------------------------------------------------------- #
def luna_payload(**overrides):
    payload = {
        "client_name": "Luna Cosmetics", "client_reference": None, "client_country": "United States",
        "services_requested": ["warehousing", "last_mile"], "monthly_volume": 5000, "deadline": None,
        "deadline_text": "around August 24th", "budget_range": None,
        "contact": {"name": "Maya Chen", "role": "Founder, Luna Cosmetics", "email": None},
    }
    payload.update(overrides)
    return payload


def test_a_valid_llm_extraction_is_used():
    extracted = metadata_agent.extract_metadata(load(INFORMAL), llm=ScriptedLLM(metadata=luna_payload()))

    assert extracted.source == "llm"
    assert extracted.monthly_volume == 5000
    assert extracted.currency == "USD"
    assert extracted.warnings == []


def test_an_invented_volume_is_dropped():
    extracted = metadata_agent.extract_metadata(load(INFORMAL), llm=ScriptedLLM(metadata=luna_payload(monthly_volume=7500)))

    assert extracted.monthly_volume is None
    assert any("7500" in warning for warning in extracted.warnings)


def test_a_date_without_year_in_the_rfp_is_not_turned_into_a_date():
    extracted = metadata_agent.extract_metadata(load(INFORMAL), llm=ScriptedLLM(metadata=luna_payload(deadline="2026-08-24")))

    assert extracted.deadline is None
    assert "August 24th" in extracted.deadline_text
    assert any("deadline" in warning for warning in extracted.warnings)


def test_an_explicitly_excluded_service_is_removed_even_if_the_llm_asks_for_it():
    payload = {
        "client_name": "ModaViva", "client_country": "Spain",
        "services_requested": ["warehousing", "last_mile", "reverse_logistics"],
        "monthly_volume": None, "deadline": "2026-08-28", "contact": {"name": "Elena Bosch"},
    }

    extracted = metadata_agent.extract_metadata(load(FORMAL), llm=ScriptedLLM(metadata=payload))

    assert extracted.services_requested == ["warehousing", "reverse_logistics"]
    assert "lastmile" not in extracted.departments_needed
    assert extracted.deadline == date(2026, 8, 28)
    assert any("last_mile" in warning for warning in extracted.warnings)


def test_currency_and_departments_never_come_from_the_llm():
    payload = luna_payload(currency="EUR", departments_needed=["reverse"])

    extracted = metadata_agent.extract_metadata(load(INFORMAL), llm=ScriptedLLM(metadata=payload))

    assert extracted.currency == "USD"
    assert extracted.departments_needed == ["warehouse", "lastmile"]


def test_a_client_name_that_is_not_in_the_document_is_replaced_by_the_rules():
    extracted = metadata_agent.extract_metadata(load(INFORMAL), llm=ScriptedLLM(metadata=luna_payload(client_name="Sol Beauty")))

    assert extracted.client_name == "Luna Cosmetics"
    assert any("Sol Beauty" in warning for warning in extracted.warnings)


def test_without_llm_the_rules_extract_the_metadata():
    extracted = metadata_agent.extract_metadata(load(FORMAL), llm=offline_llm)

    assert extracted.source == "rules"
    assert extracted.client_country == "Spain"
    assert any("LLM no disponible" in warning for warning in extracted.warnings)


# --------------------------------------------------------------------------- #
# Legibilidad / costo
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("fixture", "language"), [(FORMAL, "es"), (INFORMAL, "en"), (INVALID, "en")])
def test_readability_metrics_estimate_the_processing_cost(fixture, language):
    markdown = load(fixture)

    result = metrics.readability_metrics(markdown, llm_readers=3)

    assert result["language"] == language
    assert result["word_count"] > 40
    assert result["estimated_tokens"] == -(-len(markdown) // 4)
    assert result["estimated_llm_input_tokens"] == result["estimated_tokens"] * 3
    for key in ("flesch_kincaid_grade", "gunning_fog", "flesch_reading_ease", "fernandez_huerta"):
        assert isinstance(result[key], float)
    assert result["source"] in {"internal", "py-readability-metrics"}
    assert result["cost_tier"] == "bajo"


def test_a_long_dense_document_is_a_high_cost_tier():
    sentence = "La implementación interoperable de capacidades multialmacén requiere documentación exhaustiva. "
    assert metrics.readability_metrics(sentence * 400)["cost_tier"] == "alto"


def test_short_documents_use_the_internal_formulas():
    """py-readability-metrics exige 100 palabras: con menos se usan las fórmulas propias."""
    assert metrics.readability_metrics("Hello there. Send a proposal please.")["source"] == "internal"


def test_spanish_density_uses_fernandez_huerta_even_with_the_library(monkeypatch):
    """py-readability-metrics aplica Flesch-Kincaid (inglés) al español y lo infla: no decide el costo."""
    monkeypatch.setattr(
        metrics, "_library_scores",
        lambda text: {"flesch_kincaid_grade": 18.0, "flesch_reading_ease": 10.0, "gunning_fog": 20.0},
    )

    result = metrics.readability_metrics(load(FORMAL))

    assert result["source"] == "py-readability-metrics"
    assert result["flesch_kincaid_grade"] == 18.0
    assert result["fernandez_huerta"] > 50
    assert result["dense"] is False
    assert result["cost_tier"] == "bajo"


def test_dense_english_raises_the_cost_tier(monkeypatch):
    monkeypatch.setattr(
        metrics, "_library_scores",
        lambda text: {"flesch_kincaid_grade": 16.0, "flesch_reading_ease": 20.0, "gunning_fog": 18.0},
    )

    assert metrics.readability_metrics(load(INFORMAL))["cost_tier"] == "medio"
