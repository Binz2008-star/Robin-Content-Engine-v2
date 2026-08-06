import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import { ApiError, apiClient } from '../api/client';
import { ArchitectureSchemaView } from '../components/ArchitectureSchemaView';
import { ScriptGeneratorStudio } from '../components/ScriptGeneratorStudio';
import { VideoCanvasPlayer } from '../components/VideoCanvasPlayer';
import { copyTextToClipboard } from '../lib/clipboard';

describe('Copilot review regressions', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('copies text only after clipboard write succeeds', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    await expect(copyTextToClipboard('hello')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('returns false when clipboard permission is rejected', async () => {
    const writeText = vi.fn().mockRejectedValue(
      new DOMException('Permission denied', 'NotAllowedError')
    );
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    await expect(copyTextToClipboard('hello')).resolves.toBe(false);
  });

  it('shows canonical video_queue facts and no invented jobs SQL', () => {
    render(<ArchitectureSchemaView />);

    expect(screen.getByText('public.video_queue')).toBeInTheDocument();
    expect(screen.getByText('FOR UPDATE SKIP LOCKED')).toBeInTheDocument();
    expect(screen.queryByText(/CREATE TABLE jobs/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/DATABASE_URL/i)).not.toBeInTheDocument();
  });

  it('generates explicitly simulated content in demo mode', async () => {
    vi.spyOn(apiClient, 'isConfigError').mockReturnValue(false);
    vi.spyOn(apiClient, 'isDemoMode').mockReturnValue(true);

    render(<ScriptGeneratorStudio />);
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Generate Simulated Script',
      })
    );

    await waitFor(() => {
      expect(screen.getByText(/\[DEMO\]/)).toBeInTheDocument();
    });
  });

  it('shows backend unavailable in live mode without demo fallback', async () => {
    vi.spyOn(apiClient, 'isConfigError').mockReturnValue(false);
    vi.spyOn(apiClient, 'isDemoMode').mockReturnValue(false);
    vi.spyOn(apiClient, 'generateScript').mockRejectedValue(
      new ApiError(
        501,
        'Script generation backend endpoint is not implemented yet.'
      )
    );

    render(<ScriptGeneratorStudio />);
    fireEvent.click(
      screen.getByRole('button', {
        name: 'Request Backend Script',
      })
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Backend feature not available yet/i)
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/\[DEMO\]/)).not.toBeInTheDocument();
  });

  it('clears the video preview interval when unmounted', () => {
    vi.useFakeTimers();
    const { unmount } = render(<VideoCanvasPlayer />);

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Play preview',
      })
    );

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(
      screen.getByRole('button', {
        name: 'Pause preview',
      })
    ).toBeInTheDocument();

    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});
