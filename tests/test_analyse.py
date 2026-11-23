import numpy as np
import pandas as pd
import pytest

from brvm_mcp import analyse


def _cours(valeurs, debut="2024-01-01"):
    idx = pd.bdate_range(debut, periods=len(valeurs))
    return pd.DataFrame({"cloture": valeurs, "volume_fcfa": 1_000_000.0}, index=idx)


def test_perte_maximale_dates():
    c = _cours([100, 120, 90, 110]).cloture
    p = analyse.perte_maximale(c)
    assert p["perte_max_pct"] == -25.0
    assert p["sommet"] == "2024-01-02" and p["creux"] == "2024-01-03"


def test_var_cvar_minimum_30_observations():
    assert analyse.var_cvar(pd.Series([0.01] * 10)) == (None, None)
    r = pd.Series(np.linspace(-0.05, 0.05, 101))
    var, cvar = analyse.var_cvar(r)
    assert var == pytest.approx(4.5, abs=0.01)
    assert cvar > var


def test_beta_sur_dates_communes():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-01", periods=200)
    ref = pd.Series(rng.normal(0, 0.01, 200), index=idx)
    titre = 2 * ref + rng.normal(0, 0.001, 200)
    b = analyse.beta(titre.iloc[::2], ref)  # le titre n'échange qu'une séance sur deux
    assert b["observations"] == 100
    assert b["beta"] == pytest.approx(2, abs=0.05)


def test_beta_trop_peu_observations():
    idx = pd.bdate_range("2024-01-01", periods=20)
    s = pd.Series(np.arange(20) / 100, index=idx)
    assert analyse.beta(s, s)["beta"] is None


def test_mesures_titre_regulier():
    c = _cours(list(100 * 1.001 ** np.arange(253)))
    m = analyse.mesures(c, seances_calendrier=300)
    assert m["rendement_total_pct"] == pytest.approx((1.001 ** 252 - 1) * 100, abs=0.01)
    assert m["perte_max_pct"] == 0.0
    assert m["part_seances_echangees_pct"] == pytest.approx(84.3, abs=0.1)
    assert m["seances_a_la_limite_7_5_pct"] == 0


def test_mesures_compte_les_seances_a_la_limite():
    c = _cours([100, 107.5, 99.44, 100])
    assert analyse.mesures(c)["seances_a_la_limite_7_5_pct"] == 2


def test_mesures_une_seance():
    assert "erreur" in analyse.mesures(_cours([100]))


def test_reechantillonnage_mensuel_garde_les_trous():
    idx = pd.to_datetime(["2024-01-02", "2024-01-31", "2024-03-05"])
    df = pd.DataFrame({"ouverture": [1, 2, 3], "plus_haut": [1, 2, 3], "plus_bas": [1, 2, 3],
                       "cloture": [10.0, 11.0, 12.0], "volume_titres": [1, 1, 1],
                       "volume_fcfa": [5.0, 5.0, 5.0]}, index=idx)
    m = analyse.reechantillonner(df, "mois")
    assert len(m) == 2  # février sans échange : pas de ligne
    assert m["cloture"].tolist() == [11.0, 12.0]


def test_table_json():
    df = _cours([100.123456, np.nan, 101])
    t = analyse.table(df, 2)
    assert t["colonnes"][0] == "index"
    assert t["lignes_total"] == 3 and t["lignes_montrees"] == 2
    assert t["lignes"][0][1] is None
    assert isinstance(t["lignes"][0][0], str)
