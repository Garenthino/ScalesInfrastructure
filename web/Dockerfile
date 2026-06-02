FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci --only=production=false

# Copy source
COPY . .

# Build
ARG NEXT_PUBLIC_API_URL=https://dancingdragonservices.com/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

# Production image
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ARG NEXT_PUBLIC_API_URL=https://dancingdragonservices.com/api/v1
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Copy only what's needed
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/next.config.* ./
# public/ is optional — create empty dir if project doesn't have one
RUN mkdir -p public

EXPOSE 4000

CMD ["npx", "next", "start", "-p", "4000"]
