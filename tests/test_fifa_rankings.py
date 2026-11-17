from datetime import datetime,timezone
from backend.fifa_rankings import parse_rows,fetch_rankings,SOURCE

NOW=datetime(2026,11,17,9,tzinfo=timezone.utc)


def test_rendered_fifa_ranks_use_country_codes_and_explicit_live_label():
    participants=[{'id':20,'type':'national','gender':'male','short_code':'BRA'}]
    rows=[{'href':'/en/fifa-rankings/world-ranking/BRA?gender=men','rank':'6\n0','points':'1,800.36'}]
    result=parse_rows(rows,participants,NOW)
    assert result[0]['team_id']==20 and result[0]['rank']==6 and result[0]['points']==1800.36
    assert result[0]['official'] is False and result[0]['kind']=='live'
    assert result[0]['source_url']==SOURCE and result[0]['ranking_date']=='2026-11-17'


def test_invalid_and_unrelated_fifa_rows_are_not_used():
    participants=[{'id':20,'type':'national','gender':'male','short_code':'BRA'}]
    rows=[{'href':'/ranking/ARG','rank':'1','points':'2000'},
          {'href':'/ranking/BRA','rank':'','points':'1800'},
          {'href':'/ranking/BRA','rank':'6','points':'nan'}]
    assert parse_rows(rows,participants,NOW)==[]
    assert fetch_rankings({'participants':[{'id':20,'type':'domestic','name':'Club'}]},NOW)==[]
