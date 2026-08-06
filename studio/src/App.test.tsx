import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from './App';
import { apiClient } from './api/client';

describe('App component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders studio layout and navbar title', async () => {
    vi.spyOn(apiClient, 'getHealth').mockResolvedValue({ status: 'ok', database: 'connected' });
    vi.spyOn(apiClient, 'getJobs').mockResolvedValue([]);
    vi.spyOn(apiClient, 'getJobCounts').mockResolvedValue({
      pending: 0,
      processing: 0,
      rendered: 0,
      uploaded: 0,
      failed: 0,
      quarantined: 0,
      total: 0,
    });

    render(<App />);
    expect(screen.getAllByText(/Robin Engine/i)[0]).toBeInTheDocument();
  });

  it('fetches queue jobs on mount using apiClient', async () => {
    vi.spyOn(apiClient, 'getHealth').mockResolvedValue({ status: 'ok', database: 'connected' });
    const getJobsSpy = vi.spyOn(apiClient, 'getJobs').mockResolvedValue([]);
    vi.spyOn(apiClient, 'getJobCounts').mockResolvedValue({
      pending: 0,
      processing: 0,
      rendered: 0,
      uploaded: 0,
      failed: 0,
      quarantined: 0,
      total: 0,
    });

    render(<App />);
    await waitFor(() => {
      expect(getJobsSpy).toHaveBeenCalled();
    });
  });
});
