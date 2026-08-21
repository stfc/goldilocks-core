import { describe, expect, it, vi } from "vitest";

import type {
  ArchiveDownload,
  GuidedRequest,
  Recommendation,
  WorkbenchClient,
} from "../api/workbenchClient";
import { WorkbenchFailure } from "../api/workbenchClient";
import { inspection, recommendation, source } from "../test/workbenchFixtures";
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
    const reviewRequest = vi
      .fn<(request: GuidedRequest) => Promise<Recommendation>>()
      .mockResolvedValueOnce(recommendation)
      .mockRejectedValueOnce(
        new WorkbenchFailure("server_busy", "Server busy", true),
      )
      .mockResolvedValueOnce({
        ...recommendation,
        review_digest: "e".repeat(64),
      });
    const client: WorkbenchClient = {
      inspect: vi.fn().mockResolvedValue(inspection),
      review: reviewRequest,
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
    expect(workspace.getSnapshot().draft).not.toHaveProperty("pseudo_table_id");

    await workspace.dispatch({ type: "review.recompute" });
    expect(reviewRequest.mock.calls[0]?.[0]).not.toHaveProperty(
      "pseudo_table_id",
    );
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

  it("retains the valid workspace when replacement inspection fails", async () => {
    const replacement = {
      name: "broken.cif",
      format: "cif" as const,
      content: "not a structure",
    };
    const download: ArchiveDownload = {
      blob: new Blob(["zip"]),
      filename: "goldilocks.zip",
    };
    const failure = new WorkbenchFailure(
      "invalid_request",
      "Could not parse replacement.",
      false,
    );
    const client: WorkbenchClient = {
      inspect: vi
        .fn()
        .mockResolvedValueOnce(inspection)
        .mockRejectedValueOnce(failure),
      review: vi.fn().mockResolvedValue(recommendation),
      archive: vi.fn().mockResolvedValue(download),
    };
    const workspace = createWorkspace(client, vi.fn());
    await workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "review.recompute" });
    await workspace.dispatch({ type: "archive.download" });

    await workspace.dispatch({ type: "source.open", source: replacement });

    expect(workspace.getSnapshot()).toMatchObject({
      source,
      attemptedSource: replacement,
      inspection,
      review: recommendation,
      archive: download,
      operation: null,
      failure,
      failureOperation: "inspect",
    });
  });
  it("discards an archive response when the draft changes in flight", async () => {
    let resolveArchive: ((archive: ArchiveDownload) => void) | undefined;
    const archivePending = new Promise<ArchiveDownload>((resolve) => {
      resolveArchive = resolve;
    });
    const client: WorkbenchClient = {
      inspect: vi.fn().mockResolvedValue(inspection),
      review: vi.fn().mockResolvedValue(recommendation),
      archive: vi.fn().mockReturnValue(archivePending),
    };
    const saveArchive = vi.fn<(archive: ArchiveDownload) => void>();
    const workspace = createWorkspace(client, saveArchive);
    await workspace.dispatch({ type: "source.open", source });
    await workspace.dispatch({ type: "review.recompute" });

    const download = workspace.dispatch({ type: "archive.download" });
    await workspace.dispatch({
      type: "draft.patch",
      hints: { k_grid: [5, 5, 5] },
    });
    resolveArchive?.({
      blob: new Blob(["stale zip"]),
      filename: "stale.zip",
    });
    await download;

    expect(saveArchive).not.toHaveBeenCalled();
    expect(workspace.getSnapshot()).toMatchObject({
      operation: null,
      archive: null,
      reviewStale: true,
    });
  });
});
