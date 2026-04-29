# Sample Data Sources

Use small, clearly licensed samples first. The goal is not to build a huge
corpus immediately; it is to prove ingestion, metadata extraction, embeddings,
search, and file serving end to end.

## Images

Recommended starter order:

1. Pexels API: free stock photos and videos; good for realistic marketing-like
   images.
2. Pixabay API: royalty-free images and videos; simple API and category search.
3. Wikimedia Commons: best when you want explicit public-domain or Creative
   Commons licensing metadata.
4. COCO: useful if you want image captions and object annotations.
5. Open Images: very large annotated image dataset; better after the pipeline
   already works.

Store local samples under:

```text
storage/assets/images/
```

Suggested first sample:

```text
storage/assets/images/food/
storage/assets/images/retail/
storage/assets/images/people/
storage/assets/images/packaging/
```

## PDFs

Recommended starter order:

1. Your existing RAG project docs from `C:\Projects\old projects\interview_prep\projects\RAG`.
2. arXiv PDFs for technical/research document search.
3. PubMed Central Open Access Subset for biomedical PDFs with reuse licenses.
4. GovInfo for public government PDFs and metadata.
5. SEC EDGAR filings for business/finance document retrieval.

Store local samples under:

```text
storage/assets/pdfs/
```

For the first milestone, use 20-50 images and 10-20 PDFs. That is enough to
validate ingestion quality, retrieval quality, file serving, and answer style
without creating noise.

## Licensing Notes

Keep the original source URL and license metadata in `assets.metadata`. For
images with people, brands, logos, or artwork, licensing can be more subtle
than "free download"; keep samples for internal development unless you have
verified usage rights.
