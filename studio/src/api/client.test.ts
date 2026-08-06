import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiClient } from './client';

describe('apiClient', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    apiClient.resetDemoData();
  });

  it('reports demo and configuration status as booleans', () => {
    expect(typeof apiClient.isDemoMode()).toBe('boolean');
    expect(typeof apiClient.isConfigError()).toBe('boolean');
  });

  it('returns demo health without claiming a real database connection', async () => {
    vi.spyOn(apiClient, 'isConfigError').mockReturnValue(false);
    vi.spyOn(apiClient, 'isDemoMode').mockReturnValue(true);

    const health = await apiClient.getHealth();

    expect(health.status).toBe('ok');
    expect(health.database).toBe('demo-only');
    expect(health.demo_mode).toBe(true);
  });

  it('never silently returns demo jobs when the live API fails', async () => {
    vi.spyOn(apiClient, 'isConfigError').mockReturnValue(false);
    vi.spyOn(apiClient, 'isDemoMode').mockReturnValue(false);

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => 'Database connection failed',
    } as unknown as Response);

    await expect(
      apiClient.getJobs({ maxRetries: 0 })
    ).rejects.toBeInstanceOf(ApiError);
  });

  it('passes an AbortSignal to live fetch calls', async () => {
    vi.spyOn(apiClient, 'isConfigError').mockReturnValue(false);
    vi.spyOn(apiClient, 'isDemoMode').mockReturnValue(false);

    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        jobs: [],
        counts: {
          pending: 0,
          processing: 0,
          rendered: 0,
          uploaded: 0,
          failed: 0,
          quarantined: 0,
          total: 0,
        },
      }),
    } as unknown as Response);
    globalThis.fetch = fetchSpy;

    const controller = new AbortController();
    await apiClient.getJobs({ signal: controller.signal });

    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/jobs'),
      expect.objectContaining({
        signal: expect.any(AbortSignal),
      })
    );
  });

  it('generates clearly labelled simulated content in demo mode', async () => {
    vi.spyOn(apiClient, 'isConfigError').mockReturnValue(false);
    vi.spyOn(apiClient, 'isDemoMode').mockReturnValue(true);
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const generated = await apiClient.generateScript({
      game_name: 'Fortnite',
      topic: 'لقطة فوز',
      style: 'حماسي',
    });

    expect(generated.title).toContain('[DEMO]');
    expect(generated.description).toContain('Simulated');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('returns 501 in live mode without calling an unapproved endpoint', async () => {
    vi.spyOn(apiClient, 'isConfigError').mockReturnValue(false);
    vi.spyOn(apiClient, 'isDemoMode').mockReturnValue(false);
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    await expect(
      apiClient.generateScript({
        game_name: 'Fortnite',
        topic: 'لقطة فوز',
      })
    ).rejects.toMatchObject({
      status: 501,
      message: 'Script generation backend endpoint is not implemented yet.',
    });

    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
