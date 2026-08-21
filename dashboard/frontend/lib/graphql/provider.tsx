"use client";

import { Provider } from "urql";
import { client } from "./client";

export function GraphQLProvider({ children }: { children: React.ReactNode }) {
  return <Provider value={client}>{children}</Provider>;
}
