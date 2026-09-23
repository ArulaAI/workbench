import type { ReactElement } from "react";
import { vi } from "vitest";
import { render } from "@testing-library/react";
import type { RepositoryDigestBuildStatus, RepositoryDigestData } from "@/lib/graphql/queries/repository-digest";
import { RepositoryDigestProvider } from "@/lib/hooks/useRepositoryDigest";
import { baseDigest, baseStatus } from "./fixtures";

/**
 * Every /digest/* page now reads its data via RepositoryDigestContext
 * (see useRepositoryDigest.tsx) rather than calling the urql hooks
 * itself, so every render of a Digest page in tests needs the same
 * provider wrapping it — otherwise useRepositoryDigest() throws
 * "must be called within a RepositoryDigestProvider". The provider
 * itself calls the exact same useQuery/useMutation/useSubscription each
 * test file already mocks via vi.mock("urql", ...), so nothing about
 * the existing mock setup below needs to change — only the render call.
 */
export function renderDigestPage(ui: ReactElement) {
  return render(<RepositoryDigestProvider>{ui}</RepositoryDigestProvider>);
}

/**
 * Shared urql mock wiring for every Digest page test. Each test file must
 * still declare its own `vi.mock("urql", ...)` (vitest hoists mock calls
 * within the file that makes them, so that can't move here) and pass in
 * the three `vi.mocked(...)` handles it derives from that mock.
 */
export function setupUrqlHooks(
  mockedUseQuery: ReturnType<typeof vi.fn>,
  mockedUseMutation: ReturnType<typeof vi.fn>,
  mockedUseSubscription: ReturnType<typeof vi.fn>,
  overrides: {
    digest?: RepositoryDigestData | null;
    fetching?: boolean;
    error?: Error | null;
    status?: RepositoryDigestBuildStatus | null;
    executeRefresh?: ReturnType<typeof vi.fn>;
  } = {},
) {
  const {
    digest = baseDigest,
    fetching = false,
    error = null,
    status = baseStatus,
    executeRefresh = vi.fn().mockResolvedValue({ data: { refreshRepositoryDigest: { accepted: true } } }),
  } = overrides;

  mockedUseQuery.mockImplementation((opts: any) => {
    const query = String(opts.query);
    if (query.includes("RepositoryDigestStatus")) {
      return [
        { data: status ? { repositoryDigestStatus: status } : undefined, fetching: false, error: null, stale: false, extensions: undefined },
        vi.fn(),
      ];
    }
    return [
      { data: { repositoryDigest: digest }, fetching, error, stale: false, extensions: undefined },
      vi.fn(),
    ];
  });

  mockedUseMutation.mockReturnValue([
    { fetching: false, stale: false, error: undefined, extensions: undefined, data: undefined },
    executeRefresh,
  ]);

  mockedUseSubscription.mockReturnValue([
    { data: undefined, error: null, fetching: false, stale: false, extensions: undefined },
    vi.fn(),
  ]);

  return { executeRefresh };
}

export type UrqlHookOverrides = Parameters<typeof setupUrqlHooks>[3];
