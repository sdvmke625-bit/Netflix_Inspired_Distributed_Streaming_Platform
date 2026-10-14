# Frontend

This directory contains the React and TypeScript browser client for the
Netflix-Inspired Distributed Streaming Platform. It provides the login,
catalog browsing, movie details, playback, Continue Watching, and Watch Again
screens. The frontend is built with Vite and served by Nginx in the project's
Docker Compose stack. Local video files are served from `public/videos/`.

## Run the complete application

From the project root, build and start the services:

```sh
docker compose up --build -d
```

Open <http://localhost:3000>. The frontend connects to the Catalog and
Streaming Session endpoints configured through the `VITE_*` build arguments
in `docker-compose.yml`. For service setup, account registration, and
application usage, see the root-level `Installation_Guide.txt` and
`Usage_Manual.txt`.

## Frontend scripts

Run these commands from this directory after installing the dependencies
declared in `package.json`:

```sh
npm run dev
npm run build
npm run lint
```

The development server is for frontend development; the Compose configuration
is the supported way to run the complete application. The package currently
has no automated test script.
