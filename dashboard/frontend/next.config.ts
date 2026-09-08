import type { NextConfig } from "next";
import { createHash } from "node:crypto";

const graphqlUrl = process.env.NEXT_PUBLIC_GRAPHQL_URL;
const isolatedDistDir = graphqlUrl
  ? `.next-${createHash("sha256").update(graphqlUrl).digest("hex").slice(0, 10)}`
  : ".next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: __dirname,
  // Multiple Workbench projects can run this shared frontend against
  // different dashboard APIs. A backend-specific cache prevents concurrent
  // dev servers from overwriting each other's compiled GraphQL endpoint.
  distDir: process.env.SPEED_NEXT_DIST_DIR || isolatedDistDir,
  // The experiment checks application sources separately from legacy test
  // fixtures. Vitest still executes its tests; no application errors are ignored.
  ...(process.env.SPEED_TYPESCRIPT_CONFIG
    ? { typescript: { tsconfigPath: process.env.SPEED_TYPESCRIPT_CONFIG } }
    : {}),
};

export default nextConfig;
