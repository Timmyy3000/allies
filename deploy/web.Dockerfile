# Built from the repository root: docker build -f deploy/web.Dockerfile .
FROM oven/bun:1.2.20

WORKDIR /app
COPY package.json bun.lock ./
COPY apps/web/package.json apps/web/
COPY apps/mobile/package.json apps/mobile/
COPY packages/ally-motion/package.json packages/ally-motion/
COPY packages/cloud-client/package.json packages/cloud-client/
RUN bun install --frozen-lockfile

COPY apps/web apps/web
COPY packages packages

# NEXT_PUBLIC_* values are compiled into the browser bundle.
ARG NEXT_PUBLIC_CLOUD_API_URL
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_ACTIVITY_SSE_ENABLED=true
ARG NEXT_PUBLIC_CREATION_WAKE_ENABLED=true
ARG NEXT_PUBLIC_WAITLIST_ENABLED=false
ARG NEXT_PUBLIC_POSTHOG_HOST=
ARG NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN=
ENV NEXT_PUBLIC_CLOUD_API_URL=$NEXT_PUBLIC_CLOUD_API_URL \
    NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL \
    NEXT_PUBLIC_ACTIVITY_SSE_ENABLED=$NEXT_PUBLIC_ACTIVITY_SSE_ENABLED \
    NEXT_PUBLIC_CREATION_WAKE_ENABLED=$NEXT_PUBLIC_CREATION_WAKE_ENABLED \
    NEXT_PUBLIC_WAITLIST_ENABLED=$NEXT_PUBLIC_WAITLIST_ENABLED \
    NEXT_PUBLIC_POSTHOG_HOST=$NEXT_PUBLIC_POSTHOG_HOST \
    NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN=$NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN \
    NEXT_TELEMETRY_DISABLED=1

RUN bun run build:web
EXPOSE 3000
WORKDIR /app/apps/web
CMD ["bun", "run", "start"]
