import { describe, expect, it, vi } from "vitest";

import type {
  ArchiveDownload,
  GuidedRequest,
  Recommendation,
  WorkbenchClient,
} from "../api/workbenchClient";
import { WorkbenchFailure } from "../api/workbenchClient";
import {
  inspection,
  recommendation,
  source,
} from "../test/workbenchFixtures";
import { createWorkspace } from "./workspace";


describe("Workspace", () => {
  it("retains stale trustworthy outputs across overrides and retryable failures", async () => {
    const download: ArchiveDownload = {
      blob: new Blob(["zip"]),
      filename: "goldilocks.zip",
    };
    const archiveRequest = vi
      .fn<
        (
          request: GuidedRequest,
          reviewDigest: string,
        ) => Promise<ArchiveDownload>
      >()
      .mockResolvedValue(download);
    const client: WorkbenchClient = {
      inspect: vi.fn().mockResolvedValue(inspection),
      review: vi
        .fn<(request: GuidedRequest) => Promise<Recommendation>>()
        .mockResolvedValueOnce(recommendation)
        .mockRejectedValueOnce(
          new WorkbenchFailure("server_busy", "Server busy", true),
        )
        .mockResolvedValueOnce({
          ...recommendation,
          review_digest: "e".repeat(64),
        }),
      archive: archiveRequest,
    };
    const saveArchive = vi.fn<(archive: ArchiveDownload) => void>();
    const workspace = createWorkspace(client, saveArchive);
    const updates = vi.fn();
    const unsubscribe = workspace.subscribe(updates);

    await workspace.dispatch({ type: "source.open", source });
    expect(workspace.getSnapshot()).toMatchObject({
      source,
      operation: null,
      inspection,
      review: null,
      failure: null,
    });

    await workspace.dispatch({ type: "review.recompute" });
    expect(workspace.getSnapshot()).toMatchObject({
      review: recommendation,
      reviewStale: false,
    });

    await workspace.dispatch({
      type: "draft.patch",
      hints: { k_grid: [5, 5, 5] },
    });
    expect(workspace.getSnapshot()).toMatchObject({
      review: recommendation,
      reviewStale: true,
    });

    await workspace.dispatch({ type: "review.recompute" });
    expect(workspace.getSnapshot()).toMatchObject({
      review: recommendation,
      reviewStale: true,
      operation: null,
      failure: { kind: "server_busy", retryable: true },
    });

    await workspace.dispatch({ type: "review.recompute" });
    expect(workspace.getSnapshot()).toMatchObject({
      review: { review_digest: "e".repeat(64) },
      reviewStale: false,
      failure: null,
    });

    await workspace.dispatch({ type: "archive.download" });
    expect(archiveRequest).toHaveBeenCalledWith(
      expect.objectContaining({ hints: { k_grid: [5, 5, 5] } }),
      "e".repeat(64),
    );
    expect(saveArchive).toHaveBeenCalledWith(download);
    expect(workspace.getSnapshot()).toMatchObject({
      archive: download,
      archiveStale: false,
    });

    await workspace.dispatch({
      type: "draft.patch",
      intent: { pseudo_accuracy: "precision" },
    });
    expect(workspace.getSnapshot()).toMatchObject({
      archive: download,
      archiveStale: true,
      reviewStale: true,
    });
    expect(updates).toHaveBeenCalled();
    unsubscribe();
  });
});
