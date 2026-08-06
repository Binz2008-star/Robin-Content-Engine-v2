/**
 * Raw environment variable values
 */
export const RAW_DEMO_MODE = import.meta.env.VITE_DEMO_MODE;
export const RAW_API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

/**
 * Demo mode is ONLY active when VITE_DEMO_MODE explicitly equals exact string 'true'.
 * Values like '1', 'yes', 'TRUE', or undefined are treated as false (live mode).
 * Silent fallback to demo data on live API failure is strictly forbidden when this is false.
 */
export const IS_DEMO_MODE = RAW_DEMO_MODE === 'true';

/**
 * Cleaned API Base URL. Empty string if not defined.
 */
export const API_BASE_URL = (RAW_API_BASE_URL || '').trim().replace(/\/$/, '');

/**
 * Configuration error if live mode is active (IS_DEMO_MODE is false) but VITE_API_BASE_URL is missing.
 */
export const IS_CONFIG_ERROR = !IS_DEMO_MODE && API_BASE_URL === '';

/**
 * Polling interval must be at least 10 seconds (10,000 ms).
 */
export const POLLING_INTERVAL_MS = 10000;

/**
 * Request timeout default: 10,000 ms (10 seconds).
 */
export const REQUEST_TIMEOUT_MS = 10000;
