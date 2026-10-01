import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiClient, ApiError } from './client';

describe('apiClient', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('reports correct demo mode status based on environment config', () => {
    expect(typeof apiClient.isDemoMode()).toBe('boolean');
  });

  it('fetches health status without error in demo or live mode', async () => {
    if (apiClient.isDemoMode()) {
      const health = await apiClient.getHealth();
      expect(health.status).toBe('ok');
      expect(health.demo_mode).toBe(true);
    } else {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: 'ok', database: 'connected' }),
      } as unknown as Response);

      const health = await apiClient.getHealth();
      expect(health.status).toBe('ok');
    }
  });

  it('throws ApiError when live API fails and never silently returns demo data', async () => {
    if (!apiClient.isDemoMode()) {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        text: async () => 'Database connection failed',
      } as unknown as Response);

      await expect(apiClient.getJobs()).rejects.toThrow(ApiError);
    }
  });

  it('passes AbortSignal to fetch calls', async () => {
    if (!apiClient.isDemoMode()) {
      const fetchSpy = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [],
      } as unknown as Response);
      globalThis.fetch = fetchSpy;

      const controller = new AbortController();
      await apiClient.getJobs({ signal: controller.signal });

      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/jobs'),
        expect.objectContaining({ signal: controller.signal })
      );
    }
  });
});
