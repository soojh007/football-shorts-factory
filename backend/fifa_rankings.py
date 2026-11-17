"""Read the rendered official FIFA table, with a bounded optional browser session."""
import argparse
from datetime import datetime,timezone
import json
import re
from urllib.parse import urlparse

SOURCE='https://inside.fifa.com/fifa-rankings/world-ranking/men'


def parse_rows(rows,participants,checked_at):
    wanted={p.get('short_code','').upper():p['id'] for p in participants
            if p.get('type')=='national' and p.get('gender')=='male' and p.get('short_code')}
    result={}
    for row in rows:
        code=urlparse(row.get('href','')).path.rstrip('/').split('/')[-1].upper()
        if code not in wanted:continue
        try:
            rank=int(re.match(r'\s*(\d+)',row['rank']).group(1))
            points=float(row['points'].replace(',','').strip())
            if not 1<=rank<=211 or not 0<points<=3000:continue
        except (ValueError,KeyError,AttributeError,TypeError):continue
        result[code]={'team_id':wanted[code],'rank':rank,'points':points,
            'ranking_date':checked_at.date().isoformat(),'official':False,
            'source_url':SOURCE,'release_source_url':SOURCE,'retrieved_at':checked_at.isoformat(),
            'kind':'live','verified_via':'rendered FIFA full table'}
    return list(result.values())


def fetch_rankings(fixture,checked_at=None):
    checked_at=checked_at or datetime.now(timezone.utc)
    participants=fixture.get('participants') or []
    if not any(p.get('type')=='national' and p.get('gender')=='male' for p in participants):return []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True,timeout=5000)
            try:
                page=browser.new_page()
                page.set_default_timeout(5000)
                page.goto(SOURCE,wait_until='domcontentloaded',timeout=15000)
                reject=page.get_by_role('button',name='Reject All',exact=True)
                if reject.count() and reject.is_visible():reject.click()
                full=page.get_by_role('button',name='Show full rankings',exact=True)
                if full.count() and full.is_visible():full.click()
                page.get_by_role('link',name=participants[0]['name'],exact=True).first.wait_for(state='visible',timeout=10000)
                # Never label the default live table as a published official release.
                text=page.locator('body').inner_text()
                if 'ranking is considered unofficial' not in text.lower():return []
                rows=page.get_by_role('row').evaluate_all('''rows => rows.map(row => {
                    const cells=Array.from(row.querySelectorAll(':scope > td'));
                    return {rank:cells[0]?.querySelector('h3')?.textContent || cells[0]?.innerText || '',
                        href:cells[1]?.querySelector('a')?.getAttribute('href') || '',
                        points:cells[5]?.querySelector('h4')?.textContent || cells[5]?.innerText || ''};
                })''')
                return parse_rows(rows,participants,checked_at)
            finally:browser.close()
    except Exception:
        # Missing Chrome, blocked pages and source timeouts omit this optional input.
        return []


def main():
    parser=argparse.ArgumentParser(description='Read FIFA live ranks from the official full table.')
    parser.add_argument('--codes',nargs='+',default=['BRA','SGP'])
    args=parser.parse_args()
    names={'BRA':'Brazil','SGP':'Singapore'}
    fixture={'participants':[{'id':i+1,'type':'national','gender':'male','short_code':code,
                'name':names.get(code,code)} for i,code in enumerate(args.codes)]}
    ranks=fetch_rankings(fixture)
    print(json.dumps({'source':SOURCE,'status':'available' if ranks else 'unavailable_optional','rankings':ranks}))


if __name__=='__main__':main()
