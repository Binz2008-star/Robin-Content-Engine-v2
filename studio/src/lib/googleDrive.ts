// Google Drive API helper for Robin Engine Studio UI

export interface GoogleDriveFile {
  id: string;
  name: string;
  mimeType: string;
  size?: string;
  thumbnailLink?: string;
  webContentLink?: string;
}

export const fetchGoogleDriveVideos = async (accessToken: string): Promise<GoogleDriveFile[]> => {
  try {
    const query = encodeURIComponent("mimeType contains 'video/' and trashed = false");
    const response = await fetch(
      `https://www.googleapis.com/drive/v3/files?q=${query}&fields=files(id,name,mimeType,size,thumbnailLink,webContentLink)&pageSize=20`,
      {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      }
    );

    if (!response.ok) {
      throw new Error(`Google Drive API error: ${response.statusText}`);
    }

    const data = await response.json();
    return data.files || [];
  } catch (err) {
    console.warn("Failed to fetch Google Drive files:", err);
    return [];
  }
};
