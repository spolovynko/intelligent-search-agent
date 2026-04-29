# Belgium-Focused Corpus Sources

This note lists good starting sources for a local Belgium-themed asset/RAG
corpus. Use it to build a first sample set for image search and PDF/document
search.

## Image Sources

### KIK-IRPA / BALaT

Best fit for Belgian heritage images.

- Site: https://www.kikirpa.be/en/information-centre/photo-library
- Database: https://balat.kikirpa.be
- Why use it: large Belgian cultural heritage photo library, covering art,
  architecture, archaeology, landscapes, historical events, folklore, and more.
- Ingestion approach: start with metadata and links; check reuse/download
  rights before storing local copies.

### State Archives of Belgium

Best fit for historical photographs, posters, iconographic collections, and
Expo 58 material.

- Site: https://www.arch.be/
- Iconographic collections: https://www.arch.be/index.php?l=en&m=online-resources&r=archives-online&sr=photographs-posters-and-other-iconographic-collections
- Search environment: https://agatha.arch.be
- Why use it: strong source for Belgian institutional and historical material.

### KBR Digital Collections

Best fit for Belgian newspapers, periodicals, maps, aerial photos, and library
heritage objects.

- Site: https://www.kbr.be/en/collections/digital-collections/
- BelgicaPress: https://www.belgicapress.be
- BelgicaPeriodicals: https://www.belgicaperiodicals.be
- Cartesius maps/aerial photographs: https://www.cartesius.be
- Note: KBR states that not all digitised material can be put online or
  downloaded because of Belgian copyright rules, so use this first as metadata
  and pointer data unless reuse rights are clear.

### Europeana

Best fit for API-driven metadata aggregation across European cultural heritage
institutions, including Belgian records.

- API: https://api.europeana.eu/en
- Why use it: useful API for searching, filtering by country/provider/type, and
  collecting metadata/licensing fields.
- Ingestion approach: use Europeana Search API to collect Belgium-related image
  records, then store `source_url`, title, provider, rights, and thumbnails.

### Wikimedia Commons

Best fit for downloadable public-domain or Creative Commons images where
licensing metadata is visible.

- API: https://commons.wikimedia.org/wiki/Commons:API
- Belgium category search: https://commons.wikimedia.org/wiki/Category:Belgium
- Ingestion approach: start with Commons categories for Belgium, Brussels,
  Antwerp, Bruges, Ghent, Belgian history, Belgian architecture, and Belgian
  maps.

## PDF / Belgian History Sources

### Journal of Belgian History / BTNG-RBHC

Best first source for contemporary Belgian history articles in PDF.

- Site: https://www.journalbelgianhistory.be/
- Open access policy: https://www.journalbelgianhistory.be/en/open-access-policy
- Example issue with downloadable PDFs: https://www.journalbelgianhistory.be/nl/journal/belgisch-tijdschrift-voor-nieuwste-geschiedenis-lv-2025-1
- Note: articles are open access under CC BY-NC 4.0, so keep license metadata.

### State Archives Publications

Best source for Belgian history monographs, catalogues, guides, and archive
research publications.

- State Archives: https://www.arch.be/
- Publications overview PDF: https://www.arch.be/news/files/docs/Overzicht_publicaties.pdf
- Studies in Belgian History sample PDF: https://orfeo.belnet.be/bitstream/handle/internal/14425/EP5722.pdf
- Why use it: official Belgian archival institution; useful for high-quality
  historical PDFs.

### KBR Digital Collections

Best source for Belgian newspapers, periodicals, maps, and born-digital
publications.

- Digital collections: https://www.kbr.be/en/collections/digital-collections/
- History databases: https://www.kbr.be/en/collections/electronic-resources/databases/databases-by-subject/history/
- Copyright guidance: https://www.kbr.be/en/digitisation/digital-collections-what-about-copyrights/
- Note: excellent for pointers/metadata; downloading full PDFs may depend on
  item rights and access rules.

### ORFEO / Belgian Open Access Repositories

Best source for Belgian institutional PDFs and research outputs.

- ORFEO Belnet examples often expose direct PDF bitstreams.
- Ingestion approach: collect PDFs with source URL, institution, title, author,
  date, language, and license when available.

## Starter Corpus Recommendation

Current local corpus:

- 150 selected image records from Wikimedia Commons.
- 40 PDFs from the Journal of Belgian History / BTNG-RBHC article archive.
- Manifests live in `storage/manifests/`.

For a first useful local sample:

- 50-100 image records:
  - 25 from Wikimedia Commons Belgium categories
  - 25 from KIK-IRPA/BALaT or State Archives as metadata/pointers
  - optional 25 from Europeana API with Belgian provider/country filters
- 20-40 PDFs:
  - 10-20 Journal of Belgian History articles
  - 5-10 State Archives publications
  - 5-10 KBR/ORFEO/public-domain Belgian history documents

Store files under:

```text
storage/assets/images/belgium/
storage/assets/pdfs/belgian-history/
```

For records that cannot be downloaded, store only metadata and `source_url`.
