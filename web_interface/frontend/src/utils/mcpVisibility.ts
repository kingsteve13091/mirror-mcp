import { AvailableTool } from '../types';

export interface MCPVisibilityTreeNode {
  key: string;
  title: string;
  children?: MCPVisibilityTreeNode[];
}

export function convertTreeSelectionToMCPVisibility(
  selectedValues: string[],
  tools: AvailableTool[],
): { allowMCPs: string[] } {
  const selected = new Set((selectedValues || []).map((item) => String(item || '').trim()).filter(Boolean));
  const servers = new Set((tools || []).map((tool) => String(tool.server || '').trim()).filter(Boolean));
  const allowMCPs = Array.from(selected).filter((item) => servers.has(item));
  return { allowMCPs };
}

export function convertMCPVisibilityToTreeSelection(
  allowMCPs: string[],
  _legacyBlockMCPTools: string[] = [],
  _tools: AvailableTool[] = [],
): string[] {
  return Array.from(new Set((allowMCPs || []).map((item) => String(item || '').trim()).filter(Boolean)));
}

export function buildMCPVisibilityTree(
  tools: AvailableTool[],
): MCPVisibilityTreeNode[] {
  const toolsByServer = new Map<string, AvailableTool[]>();
  for (const tool of tools || []) {
    const server = String(tool.server || '').trim();
    if (!server) {
      continue;
    }
    if (!toolsByServer.has(server)) {
      toolsByServer.set(server, []);
    }
    toolsByServer.get(server)?.push(tool);
  }

  return Array.from(toolsByServer.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([server, serverTools]) => ({
      key: server,
      title: server,
      children: serverTools
        .slice()
        .sort((a, b) => getToolSelectionLabel(a).localeCompare(getToolSelectionLabel(b)))
        .map((tool) => ({
          key: `${server}:${getToolSelectionKey(tool)}`,
          title: getToolSelectionLabel(tool),
        })),
    }));
}

export function getToolSelectionKey(tool: AvailableTool): string {
  return String(tool.display_name || tool.name || '').trim();
}

export function getToolSelectionLabel(tool: AvailableTool): string {
  return String(tool.display_name || tool.name || '').trim();
}
