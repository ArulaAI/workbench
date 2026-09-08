import type { NextConfig } from "next";
import { createHash } from "node:crypto";

const graphqlUrl = process.env.NEXT_PUBLIC_GRAPHQL_URL;
const isolatedDistDir = graphqlUrl
  ? `.next-${createHash("sha256").update(graphqlUrl).digest("hex").slice(0, 10)}`
  : ".next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Multiple Workbench projects can run this shared frontend against
  // different dashboard APIs. A backend-specific cache prevents concurrent
  // dev servers from overwriting each other's compiled GraphQL endpoint.
  distDir: process.env.SPEED_NEXT_DIST_DIR || isolatedDistDir,
};

export default nextConfig;
