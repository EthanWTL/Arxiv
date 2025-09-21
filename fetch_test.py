import arxiv
import json
import logging

logging.basicConfig(level=logging.INFO)

def fetch_recent_papers(category="cs.AI", max_results=5, output="test.json"):
    logging.info(f"Fetching {max_results} most recent papers from {category}...")

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
            "authors": [a.name for a in result.authors],
            "summary": result.summary,
            "published": result.published.strftime("%Y-%m-%d %H:%M:%S"),
            "url": result.entry_id,
        })

    with open(output, "w", encoding="utf-8") as f:
        json.dump(papers, f, indent=2, ensure_ascii=False)

    logging.info(f"Saved {len(papers)} papers to {output}")


if __name__ == "__main__":
    fetch_recent_papers()
