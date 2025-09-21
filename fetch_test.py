import arxiv
import json
import os
from datetime import datetime

def fetch_recent_papers(category="cs.AI", max_results=5):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    os.makedirs("paper_json", exist_ok=True)
    output = f"paper_json/{today}.json"

    search = arxiv.Search(
        query=f"cat:{category}",
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers = []
    for result in search.results():
        papers.append({
            "title": result.title,
            "published": result.published.strftime("%Y-%m-%d %H:%M:%S"),
            "category": [category],
            "summary": result.summary,
            "link": result.pdf_url,   # PDF link instead of entry_id
        })

    with open(output, "w", encoding="utf-8") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(papers)} papers to {output}")


if __name__ == "__main__":
    fetch_recent_papers()
