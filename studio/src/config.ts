export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

/**
 * Demo mode is ONLY active when VITE_DEMO_MODE explicitly equals 'true'.
 * Silent fallback to demo data on live API failure is strictly forbidden when this is false.
 */
export const IS_DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true';

/**
 * Polling interval must be at least 10 seconds (10,000 ms).
 */
export const POLLING_INTERVAL_MS = 10000;
