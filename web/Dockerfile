FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm install --only=production=false

# Copy source
COPY . .

# Build
ARG NEXT_PUBLIC_API_URL=https://dancingdragonservices.com/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ARG NEXT_PUBLIC_SOCKET_URL=https://dancingdragonservices.com
ENV NEXT_PUBLIC_SOCKET_URL=${NEXT_PUBLIC_SOCKET_URL}
ARG NEXT_PUBLIC_DEFAULT_VENUE_ID=default
ENV NEXT_PUBLIC_DEFAULT_VENUE_ID=${NEXT_PUBLIC_DEFAULT_VENUE_ID}
RUN npm run build

# Production image
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ARG NEXT_PUBLIC_API_URL=https://dancingdragonservices.com/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Copy only what's needed for standalone output
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
# public/ is optional -- create empty dir if project does not have one
RUN mkdir -p public

EXPOSE 4000

CMD ["node", "server.js"]
