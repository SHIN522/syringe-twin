"""Check that the live SVG remains a valid standalone export."""
from xml.etree import ElementTree
from dashboard_visuals import overview
from twin.engine import Engine


def test_process_overview_is_valid_svg():
    e=Engine()
    e.command('start')
    e.advance(100)
    data=e.payload()
    root=ElementTree.fromstring(overview(data['snapshot'],data['meta']))
    assert root.tag.endswith('svg')
    assert 'S2' in ''.join(root.itertext())
