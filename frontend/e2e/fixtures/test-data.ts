/** Test constants shared across E2E specs. */

export const TEST_USER = {
  email: 'test@staging.local',
  password: 'staging123',
}

export const NAMESPACES = {
  primary: 'visionvolve',
  secondary: 'united-arts',
}

export const SCREENSHOTS_DIR = 'test-results/screenshots'

/** Timeouts tuned for staging (network latency). */
export const TIMEOUTS = {
  pageLoad: 15_000,
  elementVisible: 10_000,
  apiResponse: 10_000,
  shortWait: 1_000,
  mediumWait: 2_000,
}
