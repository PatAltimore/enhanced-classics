# Enhanced Classics

A static literature website that publishes classic public-domain books with AI-generated annotation cards — historical context, scientific explanations, and cultural details surfaced inline as readers encounter them.

## How it works

Original chapter text comes from [Project Gutenberg](https://www.gutenberg.org/). A Python pipeline identifies key phrases in each chapter and generates annotation cards (summaries, Wikipedia links, Wikimedia images) using Azure AI models. The result is a folder of markdown files that the frontend reads directly — no backend, no database.

## Repo structure

```
public/              # Static site — deployed to Azure Static Web Apps
├── index.html
├── catalog.json     # Book/chapter index read by the frontend
└── books/
    └── {book-slug}/
        └── {chapter-slug}.md

book_generator/      # Python pipeline — run locally to generate content
├── generator.py     # Main CLI
├── fetch_texts.py   # Downloads and splits Gutenberg source texts
├── find_images.py   # Fetches Wikimedia images for annotation cards
├── verify_chapters.py
├── client.py        # Azure AI model client with fallback chain
├── config/
│   └── books.yaml   # Books, chapters, model chain, generation settings
└── README.md        # Full generator documentation
```

## Frontend

The site is a single `index.html` that reads `catalog.json` and the per-chapter markdown files. No build step — push to `main` and Azure Static Web Apps deploys automatically.

## Generating content

See [book_generator/README.md](book_generator/README.md) for setup and usage. The short version:

```bash
cd book_generator
pip install -r requirements.txt
cp .env.example .env   # add your Azure credentials
python fetch_texts.py --book walden
python generator.py --book walden
```

## Deployment

GitHub Actions deploys the `public/` folder to Azure Static Web Apps on every push to `main`. No build step is required — the workflow uploads the folder as-is.

## License

Source texts are in the public domain via Project Gutenberg. See [LICENSE](LICENSE) for the rest of the repo.
