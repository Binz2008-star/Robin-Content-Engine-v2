import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from './App';
import { apiClient } from './api/client';

describe('App component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders studio layout and navbar title', async () => {
    vi.spyOn(apiClient, 'isConfigError').mockReturnValue(false);
    vi.spyOn(apiClient, 'isDemoMode').mockReturnValue(false);
    vi.spyOn(apiClient, 'getHealth').mockResolvedValue({ status: 'ok', database: 'connected' });
    vi.spyOn(apiClient, 'getJobsAndCounts').mockResolvedValue({
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
    });

    await act(async () => {
      render(<App />);
    });
    expect(screen.getAllByText(/Robin Engine/i)[0]).toBeInTheDocument();
  });

  it('fetches queue jobs on mount using apiClient', async () => {
    vi.spyOn(apiClient, 'isConfigError').mockReturnValue(false);
    vi.spyOn(apiClient, 'isDemoMode').mockReturnValue(false);
    vi.spyOn(apiClient, 'getHealth').mockResolvedValue({ status: 'ok', database: 'connected' });
    const getJobsAndCountsSpy = vi.spyOn(apiClient, 'getJobsAndCounts').mockResolvedValue({
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
    });

    await act(async () => {
      render(<App />);
    });

    await waitFor(() => {
      expect(getJobsAndCountsSpy).toHaveBeenCalled();
    });
  });
});
