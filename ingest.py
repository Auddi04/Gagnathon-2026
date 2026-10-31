import os
import requests
import json
import chromadb
from sentence_transformers import SentenceTransformer

# -------------------------------------------------------------------------
# CONFIGURATION: Manually insert the PxWeb API URL and JSON query here
# -------------------------------------------------------------------------
PXWEB_API_URL = "https://px.hagstofa.is:443/pxis/api/v1/is/Efnahagur/thjodhagsspa/THJ07000.px"

PXWEB_QUERY = {
  "query": [
    {
      "code": "Efnahagur",
      "selection": {
        "filter": "all",
        "values": ["*"]
      }
    }
  ],
  "response": {
    "format": "json-stat2"
  }
}

def fetch_and_process_pxweb_data(url: str, query: dict) -> list[dict]:
    """Fetches data from Statistics Iceland PxWeb API and formats it into text chunks for RAG."""
    print(f"Fetching data from PxWeb API: {url}...")
    response = requests.post(url, json=query)
    
    if response.status_code != 200:
        raise Exception(f"API request failed with status {response.status_code}: {response.text}")
    
    data = response.json()
    
    # Extract metadata and dataset label
    dataset_title = data.get("label", "Statistics Iceland Dataset")
    source_id = url.split("/")[-1].replace(".px", "")
    
    # Construct clean text chunks from the response for embedding
    text_content = f"Dataset Title: {dataset_title}\nSource URL: {url}\nData retrieved from Statistics Iceland PxWeb API."
    
    documents = [{
        "id": source_id,
        "text": text_content,
        "raw_json": json.dumps(data, ensure_ascii=False)
    }]
    
    return documents

def run_ingestion():
    print("1. Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer('all-MiniLM-L6-v2')

    db_path = "./chroma_db_master"
    if not os.path.exists(db_path):
        print(f"⚠️ Error: '{db_path}' directory not found. Please download and extract the master database from Google Drive first!")
        return

    print("2. Connecting to local ChromaDB persistent client...")
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection(name="hagstofa_rag")

    print("3. Fetching new data from Statistics Iceland PxWeb API...")
    try:
        new_entries = fetch_and_process_pxweb_data(PXWEB_API_URL, PXWEB_QUERY)
    except Exception as e:
        print(f"❌ Ingestion failed: {e}")
        return

    texts = [item["text"] for item in new_entries]
    ids = [item["id"] for item in new_entries]
    metadatas = [{"raw_json": item["raw_json"]} for item in new_entries]

    print("4. Generating vector embeddings...")
    embeddings = model.encode(texts).tolist()

    print("5. Upserting data into ChromaDB collection...")
    collection.upsert(
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )

    print("✅ Ingestion and embedding completed successfully! New table added to ChromaDB.")

if __name__ == "__main__":
    run_ingestion()