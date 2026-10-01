"""Warning-only coupled plans; never inspect foreign sealed orders."""
import json
import pytest
from diplomind.agent import Agent
from diplomind.engine import OperationEngine
from diplomind.personalities import PERSONAS


def setup(own, foreign=()):
    eng=OperationEngine()
    for power in eng.game.powers: eng.game.clear_units(power)
    eng.game.set_units('ITALY', own)
    eng.game.set_units('TURKEY', list(foreign))
    return Agent('ITALY', PERSONAS['diplomat'], None),eng


def codes(agent,eng,orders):
    original=list(orders)
    out=agent._convoy_diagnostics(eng,orders)
    assert orders==original
    return [x['code'] for x in out]


def test_own_fleet_moving_away_cannot_convoy():
    a,e=setup(['A APU','F ION'])
    assert codes(a,e,['A APU - GRE VIA','F ION - TUN'])==['no_planned_convoy_path']
    assert codes(a,e,['A APU - GRE VIA','F ION H'])==['no_planned_convoy_path']


def test_matching_convoy_fleet_is_valid_but_wrong_army_is_not():
    a,e=setup(['A APU','F ION'])
    assert codes(a,e,['A APU - GRE VIA','F ION C A APU - GRE'])==[]
    assert codes(a,e,['A APU - GRE VIA','F ION C A NAP - GRE'])==['no_planned_convoy_path']


def test_foreign_sealed_orders_are_not_read_or_assumed():
    a,e=setup(['A APU'],['F ION'])
    e.game.powers['TURKEY'].orders={'F ION':'- TUN'}
    assert codes(a,e,['A APU - GRE VIA'])==['convoy_requires_foreign_cooperation']
    e.game.powers['TURKEY'].orders={'F ION':'C A APU - GRE'}
    assert codes(a,e,['A APU - GRE VIA'])==['convoy_requires_foreign_cooperation']


def test_multisea_route_and_inland_move():
    a,e=setup(['A NAP','F ION','F AEG'])
    assert codes(a,e,['A NAP - SMY VIA','F ION C A NAP - SMY','F AEG C A NAP - SMY'])==[]
    assert codes(a,e,['A NAP - SMY VIA','F ION C A NAP - SMY','F AEG H'])==['no_planned_convoy_path']
    assert codes(a,e,['A NAP - ROM'])==[]


def test_rejected_candidate_preserves_only_bounded_game_vocabulary():
    a,e=setup(['A APU','F ION'])
    d=[]
    assert a._resolve(['F ION - PAR','9999','FAKE_PROVIDER_SECRET_0123456789'],a._legal_flat(e),d)==[]
    assert d[0]['candidate']=='F ION - PAR'
    assert d[1]['candidate_index']==9999
    assert d[2]['candidate_omitted']=='not_bounded_game_vocabulary'
    assert 'FAKE_PROVIDER_SECRET' not in json.dumps(d)
    assert a._safe_order_candidate('A PAR - BUR hidden-private-message')=={'candidate_omitted':'not_bounded_game_vocabulary'}


def test_coast_suffix_cannot_smuggle_arbitrary_text_or_exceed_bound():
    for text in ['F SPA/NC/FAKE_PROVIDER_SECRET - MAO', 'F SPA/NC/ - MAO',
                 'F SPA/NC - MAO ' + 'X'*10000]:
        safe = Agent._safe_order_candidate(text)
        assert safe == {'candidate_omitted':'not_bounded_game_vocabulary'}
        assert 'FAKE_PROVIDER_SECRET' not in json.dumps(safe)
    assert Agent._safe_order_candidate('F SPA/NC - MAO') == {'candidate':'F SPA/NC - MAO'}


@pytest.mark.parametrize('origin,destination,sea', [('BRE','SPA','MAO'),('SPA','BRE','MAO'),('NWY','STP','BAR'),('ANK','BUL','BLA')])
def test_split_coast_province_convoy_endpoints_use_actual_coasts(origin,destination,sea):
    a,e=setup([f'A {origin}',f'F {sea}'])
    orders=[f'A {origin} - {destination} VIA',f'F {sea} C A {origin} - {destination}']
    assert set(orders).issubset(a._legal_flat(e))
    assert codes(a,e,orders)==[]


def test_new_diagnostics_survive_private_memory_restore_and_candidates_revalidate():
    from diplomind.memory import Memory
    m=Memory('ITALY')
    diagnostics=[{'code':code,'orders':['A APU - GRE VIA']} for code in
        ['no_planned_convoy_path','convoy_requires_foreign_cooperation','structured_plan_mismatch','own_nonvacating_destination']]
    diagnostics += [{'code':'unrecognized_order','orders':[],'candidate':'F ION - PAR'},
                    {'code':'unrecognized_order','orders':[],'candidate_index':9999},
                    {'code':'unrecognized_order','orders':[],'candidate':'F SPA/NC/FAKE_PROVIDER_SECRET - MAO'}]
    m.record_order_diagnostics('F1901M',diagnostics)
    n=Memory('ITALY');n.restore(m.snapshot())
    assert len(n.order_diagnostics)==7
    assert n.order_diagnostics[4]['candidate']=='F ION - PAR'
    assert n.order_diagnostics[5]['candidate_index']==9999
    assert n.order_diagnostics[6]['candidate_omitted']=='not_bounded_game_vocabulary'
    assert 'FAKE_PROVIDER_SECRET' not in json.dumps(n.snapshot())


def test_malformed_numeric_order_ids_do_not_raise_or_persist_arbitrary_text():
    a,e=setup(['A APU'])
    diagnostics=[]
    assert a._resolve(['²','9'*5000],a._legal_flat(e),diagnostics)==[]
    assert len(diagnostics)==2
    assert all(d['candidate_omitted']=='not_bounded_game_vocabulary' for d in diagnostics)


def test_unit_plan_malformed_numeric_id_is_rejected_not_raised():
    from diplomind.schemas import OrderSet
    a,e=setup(['A APU'])
    out=OrderSet(orders=['A APU H'],unit_plan=[{'unit':'A APU','order':'²'}])
    diagnostics=[]
    assert a._check_unit_plan(out,['A APU H'],a._legal_flat(e),diagnostics)==[]
    assert diagnostics[0]['code']=='structured_plan_mismatch'
