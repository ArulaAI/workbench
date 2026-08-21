import { gql } from "urql";

export const CONTEXT_BUDGET_QUERY = gql`
  query ContextBudget($feature: String) {
    contextBudget(feature: $feature) {
      summary {
        taskCount
        totalBudget
        totalUsed
        utilizationPct
        totalCuts
        underBudgetCount
        overBudgetCount
      }
      tasks {
        taskId
        title
        stage
        totalBudget
        totalUsed
        underBudget
        allocated {
          codeContext {
            budget
            used
            filesFull
            filesSkeleton
            filesDropped
          }
          taskContext {
            budget
            used
          }
          specContext {
            budget
            used
          }
          reserve
        }
        cutsMade {
          file
          originalTier
          downgradedTo
          tokensSaved
          reason
        }
        cutsCount
        tokensSaved
      }
    }
  }
`;
