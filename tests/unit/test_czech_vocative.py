"""Comprehensive tests for Czech vocative (5. pád) name declension."""

import pytest

from api.services.czech_vocative import to_vocative


class TestCzechVocativeLookup:
    """Names that must come from the lookup table (Tier 1)."""

    # --- Female names (lookup) ---
    @pytest.mark.parametrize(
        "nominative,expected",
        [
            ("Jana", "Jano"),
            ("Hana", "Hanko"),
            ("Eva", "Evo"),
            ("Kateřina", "Kateřino"),
            ("Marie", "Marie"),
            ("Lucie", "Lucie"),
            ("Petra", "Petro"),
            ("Markéta", "Markéto"),
            ("Tereza", "Terezo"),
            ("Barbora", "Barboro"),
            ("Eliška", "Eliško"),
            ("Anna", "Anno"),
            ("Veronika", "Veroniko"),
            ("Martina", "Martino"),
            ("Michaela", "Michaelo"),
            ("Pavla", "Pavlo"),
            ("Lenka", "Lenko"),
            ("Klára", "Kláro"),
            ("Simona", "Simono"),
            ("Monika", "Moniko"),
            ("Nikola", "Nikolo"),
            ("Zuzana", "Zuzano"),
            ("Kristýna", "Kristýno"),
            ("Adéla", "Adélo"),
            ("Karolína", "Karolíno"),
            ("Dominika", "Dominiko"),
            ("Gabriela", "Gabrielo"),
            ("Alena", "Aleno"),
            ("Ivana", "Ivano"),
            ("Dana", "Dano"),
            ("Renata", "Renáto"),
            ("Jaroslava", "Jaroslavo"),
            ("Ludmila", "Ludmilo"),
            ("Růžena", "Růženo"),
            ("Věra", "Věro"),
            ("Irena", "Ireno"),
            ("Helena", "Heleno"),
            ("Dagmar", "Dagmar"),
            ("Jitka", "Jitko"),
            ("Blanka", "Blanko"),
            ("Andrea", "Andreo"),
            ("Diana", "Diano"),
            ("Soňa", "Soňo"),
            ("Romana", "Romano"),
            ("Vendula", "Vendulo"),
            ("Denisa", "Deniso"),
            ("Radka", "Radko"),
            ("Šárka", "Šárko"),
            ("Táňa", "Táňo"),
            ("Aneta", "Aneto"),
        ],
    )
    def test_female_lookup(self, nominative, expected):
        vocative, source = to_vocative(nominative)
        assert vocative == expected
        assert source == "lookup"

    # --- Male names (lookup) ---
    @pytest.mark.parametrize(
        "nominative,expected",
        [
            ("Petr", "Petře"),
            ("Martin", "Martine"),
            ("Jakub", "Jakube"),
            ("Jan", "Jane"),
            ("Tomáš", "Tomáši"),
            ("David", "Davide"),
            ("Lukáš", "Lukáši"),
            ("Marek", "Marku"),
            ("Ondřej", "Ondřeji"),
            ("Michal", "Michale"),
            ("Adam", "Adame"),
            ("Filip", "Filipe"),
            ("Daniel", "Danieli"),
            ("Pavel", "Pavle"),
            ("Vojtěch", "Vojtěchu"),
            ("Matěj", "Matěji"),
            ("Jiří", "Jiří"),
            ("Karel", "Karle"),
            ("Josef", "Josefe"),
            ("Václav", "Václave"),
            ("František", "Františku"),
            ("Radek", "Radku"),
            ("Zdeněk", "Zdeňku"),
            ("Stanislav", "Stanislave"),
            ("Milan", "Milane"),
            ("Vladimír", "Vladimíre"),
            ("Roman", "Romane"),
            ("Aleš", "Aleši"),
            ("Libor", "Libore"),
            ("Miroslav", "Miroslave"),
            ("Jaroslav", "Jaroslave"),
            ("Ivan", "Ivane"),
            ("Richard", "Richarde"),
            ("Robert", "Roberte"),
            ("Patrik", "Patriku"),
            ("Štěpán", "Štěpáne"),
            ("Dominik", "Dominiku"),
            ("Vít", "Víte"),
            ("Oldřich", "Oldřichu"),
            ("Antonín", "Antoníne"),
        ],
    )
    def test_male_lookup(self, nominative, expected):
        vocative, source = to_vocative(nominative)
        assert vocative == expected
        assert source == "lookup"


class TestCzechVocativeCaseInsensitive:
    """Lookup should be case-insensitive."""

    def test_lowercase_input(self):
        vocative, source = to_vocative("jana")
        assert vocative == "Jano"
        assert source == "lookup"

    def test_uppercase_input(self):
        vocative, source = to_vocative("JANA")
        assert vocative == "Jano"
        assert source == "lookup"

    def test_mixed_case_input(self):
        vocative, source = to_vocative("jAnA")
        assert vocative == "Jano"
        assert source == "lookup"


class TestCzechVocativeRuleBased:
    """Names NOT in the lookup table, handled by rule-based fallback (Tier 2)."""

    def test_female_a_to_o(self):
        vocative, source = to_vocative("Věroslava", use_ai=False)
        assert vocative == "Věroslavo"
        assert source == "rules"

    def test_female_ka_to_ko(self):
        vocative, source = to_vocative("Drahomírka", use_ai=False)
        assert vocative == "Drahomírko"
        assert source == "rules"

    def test_female_ie_unchanged(self):
        vocative, source = to_vocative("Valerie", use_ai=False)
        assert vocative == "Valerie"
        assert source == "rules"

    def test_male_ek_to_ku(self):
        vocative, source = to_vocative("Vojtěšek", use_ai=False)
        assert vocative == "Vojtěšku"
        assert source == "rules"

    def test_male_as_to_si(self):
        vocative, source = to_vocative("Barnabáš", use_ai=False)
        assert vocative == "Barnabáši"
        assert source == "rules"

    def test_male_ej_to_eji(self):
        vocative, source = to_vocative("Oldřej", use_ai=False)
        assert vocative == "Oldřeji"
        assert source == "rules"

    def test_male_el_to_le(self):
        vocative, source = to_vocative("Abdel", use_ai=False)
        assert vocative == "Abdle"
        assert source == "rules"

    def test_male_ec_to_ce(self):
        vocative, source = to_vocative("Norec", use_ai=False)
        assert vocative == "Norče"
        assert source == "rules"

    def test_male_ik_to_iku(self):
        vocative, source = to_vocative("Boleslík", use_ai=False)
        assert vocative == "Boleslíku"
        assert source == "rules"

    def test_male_hard_consonant_add_e(self):
        vocative, source = to_vocative("Norbert", use_ai=False)
        assert vocative == "Norberte"
        assert source == "rules"

    def test_male_soft_consonant_add_i(self):
        vocative, source = to_vocative("Mikeš", use_ai=False)
        assert vocative == "Mikeši"
        assert source == "rules"

    def test_male_k_add_u(self):
        vocative, source = to_vocative("Borek", use_ai=False)
        assert vocative == "Borku"
        assert source == "rules"


class TestCzechVocativeEdgeCases:
    """Edge cases: empty, whitespace, foreign names, None."""

    def test_empty_string(self):
        vocative, source = to_vocative("")
        assert vocative == ""
        assert source == "nominative"

    def test_none_input(self):
        vocative, source = to_vocative(None)
        assert vocative == ""
        assert source == "nominative"

    def test_whitespace_only(self):
        vocative, source = to_vocative("   ")
        assert vocative == ""
        assert source == "nominative"

    def test_leading_trailing_whitespace(self):
        vocative, source = to_vocative("  Jana  ")
        assert vocative == "Jano"
        assert source == "lookup"

    def test_foreign_name_english(self):
        vocative, source = to_vocative("John", use_ai=False)
        assert isinstance(vocative, str)
        assert len(vocative) > 0
        assert source == "rules"

    def test_foreign_name_japanese(self):
        vocative, source = to_vocative("Yuki", use_ai=False)
        assert isinstance(vocative, str)
        assert len(vocative) > 0

    def test_single_letter(self):
        vocative, source = to_vocative("X", use_ai=False)
        assert isinstance(vocative, str)

    def test_name_with_diacritics_not_in_lookup(self):
        vocative, source = to_vocative("Věroslava", use_ai=False)
        assert vocative == "Věroslavo"
        assert source == "rules"

    def test_return_is_tuple(self):
        result = to_vocative("Jana")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_nominative_fallback_when_no_rule(self):
        """A name that ends in a character not covered by any rule."""
        vocative, source = to_vocative("Lǎo", use_ai=False)
        assert vocative == "Lǎo"
        assert source == "nominative"
