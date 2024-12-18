from flask import Blueprint, render_template, jsonify, request
import requests
import time
from serpapi import GoogleSearch

bp = Blueprint('api', __name__)

def get_entity_id(entity_name, concept_type=None, limit=10):
    base_url = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/entity/autocomplete/"
    params = {"query": entity_name, "limit": limit}
    if concept_type:
        params["concept"] = concept_type

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()  # HTTP 오류가 발생하면 예외 발생
        results = response.json()
        if results:
            entity_id = results[0].get("_id")
            return entity_id
        else:
            print(f"No results found for entity: {entity_name}")
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except Exception as err:
        print(f"Other error occurred: {err}")

    return None

def find_related_entities(entity_id):
    base_url = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/relations"
    params = {"e1": entity_id}

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()  # HTTP 오류가 발생하면 예외 발생
        related_entities = response.json()
        print(f"Found {len(related_entities)} related entities for ID: {entity_id}")

        # 논문 번호를 가져오는 로직 추가
        for entity in related_entities:
            if 'publications' in entity and isinstance(entity['publications'], int):
                pmid_count = entity['publications']
                pmids = fetch_pmids_for_relation(entity_id, entity['source'], entity['target'], pmid_count)
                entity['publications'] = pmids
                time.sleep(0.1)  # 각 요청 후 0.5초 대기

        return related_entities
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except Exception as err:
        print(f"Other error occurred: {err}")

    return []

def get_synonyms(term):
    base_url = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/annotations/synonyms"
    params = {"concept": term}

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        results = response.json()
        synonyms = [result['synonym'] for result in results.get('annotations', [])]
        print(f"Synonyms for {term}: {synonyms}")
        return synonyms
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except Exception as err:
        print(f"Other error occurred: {err}")

    return []

@bp.route('/')
def home():
    print("Home route accessed")
    return render_template('index.html')

@bp.route('/api/graph/<entity_name>', methods=['GET'])
def get_graph_data(entity_name):
    print(f"Graph data requested for entity: {entity_name}")
    entity_id = get_entity_id(entity_name, concept_type="gene")
    if not entity_id:
        print("Entity ID not found")
        return jsonify({"error": "Entity ID not found"}), 404

    related_entities = find_related_entities(entity_id)
    elements = []

    # 각 노드의 type 속성을 포함하고 pmid를 추가하여 데이터 생성
    for item in related_entities:
        source_id = item['source']
        target_id = item['target']
        relation_type = item['type']
        publication_details = item.get('publications', [])

        # 관계가 복수인 경우, /로 구분하여 나열
        if isinstance(relation_type, list):
            relation_type = "/".join(relation_type)

        source_type, source_name = source_id.split("_", 1)
        source_type = source_type[1:].capitalize()  # '@gene' -> 'Gene'

        target_type, target_name = target_id.split("_", 1)
        target_type = target_type[1:].capitalize()  # '@chemical' -> 'Chemical'

        # 노드 추가 (type과 pmid 포함)
        if not any('id' in node['data'] and node['data']['id'] == source_id for node in elements):
            node_data = {
                "id": source_id,
                "label": source_name,
                "type": source_type,
                "publications": publication_details  # 관련 논문의 상세 정보 추가
            }
            elements.append({"data": node_data})

        if not any('id' in node['data'] and node['data']['id'] == target_id for node in elements):
            node_data = {
                "id": target_id,
                "label": target_name,
                "type": target_type,
                "publications": publication_details  # 관련 논문의 상세 정보 추가
            }
            elements.append({"data": node_data})

        # 엣지 추가 (relation 정보 포함)
        edge_data = {
            "source": source_id,
            "target": target_id,
            "relationship": relation_type,
            "publications": publication_details  # 엣지에 논문 상세 정보 추가
        }
        elements.append({"data": edge_data})

    print(f"Returning graph data: {elements}")
    return jsonify(elements)

@bp.route('/api/publications', methods=['POST'])
def get_publication_details():
    data = request.json
    pmids = data.get('pmids', [])
    print(f"Requested PMIDs: {pmids}")
    if not pmids:
        return jsonify({"error": "No PMIDs provided"}), 400

    publication_details = fetch_publication_details(pmids)
    return jsonify(publication_details)

@bp.route('/search', methods=['GET'])
def search():
    search_term = request.args.get('search_term')
    synonyms = get_synonyms(search_term)
    search_terms = [search_term] + synonyms

    params = {
        "engine": "google_scholar",
        "q": " OR ".join(search_terms),
        "api_key": "a93cea1cff7c2d17fa6af11d740dc06f4d9fb400471185a9527a5469453f86b1",
        "num": 20
    }

    all_results = []
    page = 1

    while True:
        params["start"] = (page - 1) * params["num"]
        search = GoogleSearch(params)
        results = search.get_dict()

        if "organic_results" in results:
            all_results.extend(results["organic_results"])
            page += 1
        else:
            break

        if page > 5:
            break

    formatted_results = []
    for index, result in enumerate(all_results):
        title = result.get('title', '').replace(search_term, f'<span class="highlight">{search_term}</span>')
        snippet = result.get('snippet', '').replace(search_term, f'<span class="highlight">{search_term}</span>')
        link = result.get('link', '#')
        authors = ', '.join([author['name'] for author in result.get('publication_info', {}).get('authors', [])])
        year = result.get('publication_info', {}).get('year', '')
        journal = result.get('publication_info', {}).get('journal', '')
        citations = result.get('inline_links', {}).get('cited_by', {}).get('total', 0)
        pdf_link = result.get('resources', [{}])[0].get('link', '')
        related_link = result.get('inline_links', {}).get('related_pages_link', '')

        formatted_results.append({
            "title": title,
            "snippet": snippet,
            "link": link,
            "authors": authors,
            "year": year,
            "journal": journal,
            "citations": citations,
            "pdf_link": pdf_link,
            "related_link": related_link
        })

    return render_template('index.html', results=formatted_results)

def fetch_pmids_for_relation(entity_id, source_id, target_id, pmid_count):
    # 논문 번호를 가져오는 로직
    search_url = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/"
    search_params = {"text": f"{source_id} AND {target_id}"}

    try:
        search_response = requests.get(search_url, params=search_params)
        search_response.raise_for_status()  # HTTP 오류가 발생하면 예외 발생
        search_results = search_response.json()
        pmids = [result['pmid'] for result in search_results.get('results', [])]
        print("pmids:", pmids)
        return pmids
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except Exception as err:
        print(f"Other error occurred: {err}")

    return []

def fetch_publication_details(pmids):
    """
    PubTator3 API를 통해 논문 상세 정보를 가져오는 함수
    
    Args:
        pmids (list): PMID 목록
        
    Returns:
        list: 논문 정보 목록
    """
    base_url = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
    params = {"pmids": ",".join(map(str, pmids))}

    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        results = response.json()
        print("Fetched raw data:", results)
        
        publications = []
        for document in results.get('PubTator3', []):
            # 기본 정보 추출
            publication = {
                "pmid": document.get('pmid'),
                "journal": document.get('journal'),
                "authors": document.get('authors'),
                "date": document.get('date'),
                "title": "",
                "abstract": ""
            }
            
            # passages에서 title과 abstract 찾기
            for passage in document.get('passages', []):
                passage_type = passage.get('infons', {}).get('type', '')
                if passage_type == 'title':
                    publication['title'] = passage.get('text', '')
                elif passage_type == 'abstract':
                    publication['abstract'] = passage.get('text', '')
            
            publications.append(publication)
            
        print("Processed publications:", publications)
        return publications
        
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        if 'response' in locals():
            print(f"Response content: {response.text}")
    except Exception as err:
        print(f"Other error occurred: {err}")
        print(f"Error type: {type(err)}")

    return []