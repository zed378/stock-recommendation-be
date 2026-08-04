# Build the bundle, then ship only the bundle.
#
# Two stages because the result is static files: Node is needed to produce them
# and has no business being in the running image. The served image is nginx and
# a few hundred kilobytes of assets - no Node runtime, no npm tree, nothing
# with a package advisory to track.

FROM node:22-alpine AS build

WORKDIR /app

# Dependencies first, so editing a component does not reinstall the tree.
# `npm ci` rather than `npm install`: it installs exactly the lockfile, which
# is the difference between a reproducible build and one that drifts.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Type-check as part of the build. A frontend whose types no longer match the
# API's generated schema should fail here rather than ship and fail in a
# browser.
RUN npm run build


FROM nginx:1.27-alpine AS serve

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# Reports unhealthy while nginx is up but the bundle is missing, which is the
# failure a plain port check would call healthy.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -q -O /dev/null http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
