import json

import httpx
from bs4 import BeautifulSoup


def main():
    print("Fetching QuintoAndar...")
    url = "https://www.quintoandar.com.br/alugar/imovel/belo-horizonte-mg-brasil"
    r = httpx.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})

    soup = BeautifulSoup(r.text, 'html.parser')
    script = soup.find('script', id='__NEXT_DATA__')
    if not script:
        print("No __NEXT_DATA__ found")
        return

    data = json.loads(script.string)

    # Try to find Apollo state or pageProps
    props = data.get('props', {})
    pageProps = props.get('pageProps', {})

    # Dump keys of pageProps
    print("pageProps keys:", pageProps.keys())

    # Save the full data to a file for deeper inspection if needed
    with open('qa_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Let's see if we can find 'initialState' or 'apolloState'
    apollo_state = pageProps.get('initialApolloState', {})
    if apollo_state:
        print(f"Found Apollo state with {len(apollo_state)} keys")
        # Find a property object
        for k, v in apollo_state.items():
            if 'House' in k or 'Property' in k or v.get('__typename') == 'House':
                print(f"Example house key: {k}")
                print(json.dumps(v, indent=2)[:500])
                break

if __name__ == "__main__":
    main()
