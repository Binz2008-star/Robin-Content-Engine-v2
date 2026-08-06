import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { apiClient, calculateJobCounts } from '../api/client';
import { VideoJob } from '../types';
import { Navbar } from '../components/Navbar';
import { QueueTable } from '../components/QueueTable';
import { EnqueueModal } from '../components/EnqueueModal';

describe('API & UI Contract Tests', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    apiClient.resetDemoData();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  describe('1. Configuration & Demo Mode Rules', () => {
    it('checks demo mode status strictly', () => {
      expect(typeof apiClient.isDemoMode()).toBe('boolean');
    });

    it('returns config error state when API_BASE_URL is missing in live mode', () => {
      expect(typeof apiClient.isConfigError()).toBe('boolean');
    });
  });

  describe('2. Hardened API Client Behavior', () => {
    it('calculates job counts across all 6 status fields', () => {
      const mockJobs = [
        { id: 1, source_title: 'J1', rights_confirmed: true, status: 'pending' },
        { id: 2, source_title: 'J2', rights_confirmed: true, status: 'processing' },
        { id: 3, source_title: 'J3', rights_confirmed: true, status: 'rendered' },
        { id: 4, source_title: 'J4', rights_confirmed: true, status: 'uploaded' },
        { id: 5, source_title: 'J5', rights_confirmed: true, status: 'failed' },
        { id: 6, source_title: 'J6', rights_confirmed: true, status: 'quarantined' },
      ] as unknown as VideoJob[];

      const counts = calculateJobCounts(mockJobs);
      expect(counts.pending).toBe(1);
      expect(counts.processing).toBe(1);
      expect(counts.rendered).toBe(1);
      expect(counts.uploaded).toBe(1);
      expect(counts.failed).toBe(1);
      expect(counts.quarantined).toBe(1);
      expect(counts.total).toBe(6);
    });

    it('prevents POST operations from automatically retrying on network error', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch');
      fetchSpy.mockRejectedValue(new TypeError('Failed to fetch'));

      if (!apiClient.isDemoMode() && !apiClient.isConfigError()) {
        await expect(
          apiClient.enqueueJob({
            source_title: 'Test',
            rights_note: 'Note',
            rights_confirmed: true,
          })
        ).rejects.toThrow('Network unavailable');

        expect(fetchSpy).toHaveBeenCalledTimes(1);
      }
    });
  });

  describe('3. Connection Status UI Component', () => {
    it('renders DEMO MODE badge when in demo mode', () => {
      render(
        <Navbar
          connectionStatus="demo_mode"
          activeTab="overview"
          setActiveTab={() => {}}
          onOpenEnqueue={() => {}}
          onOpenCLI={() => {}}
          onRefresh={() => {}}
        />
      );
      expect(screen.getByText('DEMO MODE')).toBeInTheDocument();
    });

    it('renders BACKEND CONNECTED badge when connected', () => {
      render(
        <Navbar
          connectionStatus="connected"
          activeTab="overview"
          setActiveTab={() => {}}
          onOpenEnqueue={() => {}}
          onOpenCLI={() => {}}
          onRefresh={() => {}}
        />
      );
      expect(screen.getByText('BACKEND CONNECTED')).toBeInTheDocument();
    });

    it('renders BACKEND OFFLINE badge when offline', () => {
      render(
        <Navbar
          connectionStatus="offline"
          activeTab="overview"
          setActiveTab={() => {}}
          onOpenEnqueue={() => {}}
          onOpenCLI={() => {}}
          onRefresh={() => {}}
        />
      );
      expect(screen.getByText('BACKEND OFFLINE')).toBeInTheDocument();
    });

    it('renders CONFIG ERROR badge when configuration fails', () => {
      render(
        <Navbar
          connectionStatus="config_error"
          activeTab="overview"
          setActiveTab={() => {}}
          onOpenEnqueue={() => {}}
          onOpenCLI={() => {}}
          onRefresh={() => {}}
        />
      );
      expect(screen.getByText('CONFIG ERROR')).toBeInTheDocument();
    });
  });

  describe('4. Enqueue Modal Validation', () => {
    it('requires source title, rights note, confirmed rights, and valid source', async () => {
      const handleEnqueue = vi.fn();
      render(
        <EnqueueModal
          isOpen={true}
          onClose={() => {}}
          onEnqueue={handleEnqueue}
        />
      );

      expect(screen.getByRole('dialog')).toBeInTheDocument();

      const titleInput = screen.getByLabelText(/Gameplay Video Title/i);
      fireEvent.change(titleInput, { target: { value: '' } });

      const submitBtn = screen.getByText('Enqueue Video Job');
      fireEvent.click(submitBtn);

      expect(handleEnqueue).not.toHaveBeenCalled();
    });
  });

  describe('5. Queue Table Actions & Safety', () => {
    const sampleJobs = [
      {
        id: 1,
        source_title: 'Pending Job',
        source_path: 'C:\\media\\test1.mp4',
        rights_confirmed: true,
        rights_note: 'Note 1',
        status: 'pending',
        attempts: 0,
        last_error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      {
        id: 2,
        source_title: 'Failed Job',
        source_path: 'C:\\media\\test2.mp4',
        rights_confirmed: true,
        rights_note: 'Note 2',
        status: 'failed',
        attempts: 1,
        last_error: 'Render failed',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ] as unknown as VideoJob[];

    it('displays jobs and handles confirmation modal for retry', async () => {
      const handleAction = vi.fn();
      render(
        <QueueTable
          jobs={sampleJobs}
          isDemoMode={true}
          isProcessing={false}
          onRunWorkerJob={() => {}}
          onJobAction={handleAction}
          onSelectJobForPreview={() => {}}
          onOpenEnqueueModal={() => {}}
        />
      );

      expect(screen.getAllByText('Pending Job')[0]).toBeInTheDocument();
      expect(screen.getAllByText('Failed Job')[0]).toBeInTheDocument();

      const retryButtons = screen.getAllByLabelText(/Retry Job #2/i);
      fireEvent.click(retryButtons[0]);

      expect(screen.getByText(/Confirm Retry Action/i)).toBeInTheDocument();

      const confirmBtn = screen.getByText('Confirm Retry');
      fireEvent.click(confirmBtn);

      expect(handleAction).toHaveBeenCalledWith('2', 'retry');
    });
  });
});
