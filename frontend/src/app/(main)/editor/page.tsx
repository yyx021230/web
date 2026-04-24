"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import {
  LayoutGrid, Square, Type, ImageIcon, Layers, Wand2,
  Eye, EyeOff, Lock, Unlock, Search, Plus,
  Copy, Trash2, ArrowUp, ArrowDown,
  AlignCenter, AlignLeft, AlignRight, Bold, Italic, Underline,
  Circle, Triangle,
  MinusIcon, Star, Hexagon, ArrowRight, Sparkles,
  Image, Crop,
  ZoomIn, ZoomOut, Palette, Maximize2,
  FlipHorizontal, FlipVertical,
  Loader2, Undo2, Redo2, Save, Download,
} from "lucide-react";
import { useEditorContext } from "@/contexts/EditorContext";
import { editorApi, type Template as BackendTemplate, type Material as BackendMaterial } from "@/services/editorApi";
import { getTemplateList, getTemplateMetaForFolder, type TemplateMeta } from "@/services/templateLoader";
import { gaodingToFabric } from "@/utils/gaodingToFabric";
import { useFabricCanvas } from "@/hooks/useFabricCanvas";

/* ============ Types ============ */

interface CanvasAttr {
  id: string;
  name: string;
  w: number;
  h: number;
  bgColor: string;
  bg?: string;
  bgImage?: string;
  /** Fabric JSON content for this canvas — enables thumbnail previews when inactive */
  contentJson?: string;
}

/* ============ Constants ============ */

const mockBackgrounds = [
  { id: "bg1", name: "纯白", type: "color", value: "#ffffff" },
  { id: "bg2", name: "浅灰", type: "color", value: "#f8fafc" },
  { id: "bg3", name: "深蓝", type: "color", value: "#0f172a" },
  { id: "bg8", name: "暗夜", type: "color", value: "#1a1a2e" },
  { id: "bg9", name: "薄荷绿", type: "color", value: "#d1fae5" },
  { id: "bg10", name: "薰衣草", type: "color", value: "#ede9fe" },
  { id: "bg20", name: "奶油白", type: "color", value: "#fefce8" },
  { id: "bg21", name: "天蓝", type: "color", value: "#e0f2fe" },
  { id: "bg22", name: "玫瑰粉", type: "color", value: "#fce7f3" },
  { id: "bg23", name: "纯黑", type: "color", value: "#000000" },
  { id: "bg24", name: "深绿", type: "color", value: "#052e16" },
  { id: "bg25", name: "暖沙", type: "color", value: "#fef3c7" },
  { id: "bg4", name: "渐变蓝紫", type: "gradient", value: "linear-gradient(135deg, #6366f1, #a855f7)" },
  { id: "bg5", name: "渐变粉橙", type: "gradient", value: "linear-gradient(135deg, #ec4899, #f59e0b)" },
  { id: "bg6", name: "渐变青蓝", type: "gradient", value: "linear-gradient(135deg, #10b981, #3b82f6)" },
  { id: "bg7", name: "暖色渐变", type: "gradient", value: "linear-gradient(135deg, #ef4444, #f59e0b)" },
  { id: "bg30", name: "紫罗兰", type: "gradient", value: "linear-gradient(135deg, #667eea, #764ba2)" },
  { id: "bg31", name: "日落余晖", type: "gradient", value: "linear-gradient(135deg, #f093fb, #f5576c)" },
  { id: "bg32", name: "极光绿", type: "gradient", value: "linear-gradient(135deg, #43e97b, #38f9d7)" },
  { id: "bg33", name: "深海蓝", type: "gradient", value: "linear-gradient(135deg, #0c3483, #a2b6df, #6b8dd6)" },
  { id: "bg34", name: "暮光之城", type: "gradient", value: "linear-gradient(135deg, #4a00e0, #8e2de2)" },
  { id: "bg35", name: "薄荷清新", type: "gradient", value: "linear-gradient(135deg, #96fbc4, #f9f586)" },
  { id: "bg36", name: "暗夜渐变", type: "gradient", value: "linear-gradient(135deg, #232526, #66737a)" },
  { id: "bg37", name: "珊瑚海", type: "gradient", value: "linear-gradient(135deg, #ff9a9e, #fad0c4, #ffd1ff)" },
  { id: "bg38", name: "金属银", type: "gradient", value: "linear-gradient(135deg, #e0e0e0, #bdbdbd, #e0e0e0)" },
  { id: "bg39", name: "赛博朋克", type: "gradient", value: "linear-gradient(135deg, #fc466b, #3f5efb)" },
  { id: "bg11", name: "几何图案", type: "gradient", value: "linear-gradient(135deg, #667eea 25%, #764ba2 25%, #764ba2 50%, #667eea 50%, #667eea 75%, #764ba2 75%)" },
  { id: "bg12", name: "条纹", type: "gradient", value: "repeating-linear-gradient(45deg, #6366f1, #6366f1 10px, #818cf8 10px, #818cf8 20px)" },
  { id: "bg40", name: "点阵网格", type: "gradient", value: "radial-gradient(circle, #d1d5db 1px, transparent 1px)" },
  { id: "bg41", name: "方格纸", type: "gradient", value: "linear-gradient(#e5e7eb 1px, transparent 1px), linear-gradient(90deg, #e5e7eb 1px, transparent 1px)" },
  { id: "bg42", name: "斜纹", type: "gradient", value: "repeating-linear-gradient(-45deg, #f0f0f0, #f0f0f0 5px, #ffffff 5px, #ffffff 10px)" },
  { id: "bg43", name: "同心圆", type: "gradient", value: "radial-gradient(circle at center, #6366f1 2px, transparent 2px)" },
  { id: "bg44", name: "棋盘格", type: "gradient", value: "linear-gradient(45deg, #e5e7eb 25%, transparent 25%), linear-gradient(-45deg, #e5e7eb 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #e5e7eb 75%), linear-gradient(-45deg, transparent 75%, #e5e7eb 75%)" },
];

const elementShapes = [
  { id: "rect", icon: Square, label: "矩形" },
  { id: "circle", icon: Circle, label: "圆形" },
  { id: "triangle", icon: Triangle, label: "三角形" },
  { id: "star", icon: Star, label: "星形" },
  { id: "hexagon", icon: Hexagon, label: "六边形" },
  { id: "line", icon: MinusIcon, label: "线条" },
  { id: "arrow", icon: ArrowRight, label: "箭头" },
  { id: "diamond", icon: LayoutGrid, label: "菱形" },
];

const layerTypeConfig: Record<string, { icon: string; color: string }> = {
  rect: { icon: "▬", color: "bg-blue-100 text-blue-600" },
  circle: { icon: "●", color: "bg-purple-100 text-purple-600" },
  triangle: { icon: "▲", color: "bg-green-100 text-green-600" },
  star: { icon: "★", color: "bg-yellow-100 text-yellow-600" },
  hexagon: { icon: "⬡", color: "bg-teal-100 text-teal-600" },
  line: { icon: "╱", color: "bg-gray-100 text-gray-600" },
  arrow: { icon: "→", color: "bg-orange-100 text-orange-600" },
  diamond: { icon: "◆", color: "bg-indigo-100 text-indigo-600" },
  text: { icon: "T", color: "bg-amber-100 text-amber-600" },
  image: { icon: "🖼", color: "bg-pink-100 text-pink-600" },
  group: { icon: "▤", color: "bg-cyan-100 text-cyan-600" },
};

const textColors = ["#0f172a", "#64748b", "#94a3b8", "#ffffff", "#ef4444", "#f59e0b", "#22c55e", "#3b82f6", "#8b5cf6", "#ec4899", "#06b6d4"];
const shapeDefaultColors = ["#6366f1", "#8b5cf6", "#ec4899", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#06b6d4"];
/** 与稿定 layouts 常见画板一致，全编辑器默认画板 */
const DEFAULT_CANVAS_W = 1242;
const DEFAULT_CANVAS_H = 1656;

const presetSizes = [
  { name: "手机海报", w: 1080, h: 1920, ratio: "9:16", cat: "海报" },
  { name: "横版海报", w: 1920, h: 1080, ratio: "16:9", cat: "海报" },
  { name: "小红书配图", w: 1242, h: 1656, ratio: "3:4", cat: "社交媒体" },
  { name: "公众号首图", w: 900, h: 383, ratio: "2.35:1", cat: "社交媒体" },
  { name: "公众号次图", w: 500, h: 500, ratio: "1:1", cat: "社交媒体" },
  { name: "文章长图", w: 1080, h: 3000, ratio: "9:25", cat: "社交媒体" },
  { name: "PPT 演示", w: 1920, h: 1080, ratio: "16:9", cat: "演示" },
  { name: "PPT 标准", w: 1920, h: 1440, ratio: "4:3", cat: "演示" },
  { name: "抖音封面", w: 1080, h: 1440, ratio: "3:4", cat: "视频" },
  { name: "B站封面", w: 1920, h: 1080, ratio: "16:9", cat: "视频" },
  { name: "名片", w: 900, h: 540, ratio: "5:3", cat: "印刷" },
  { name: "A4 文档", w: 794, h: 1123, ratio: "A4", cat: "印刷" },
];

/* ============ Component ============ */

export default function EditorPage() {
  const ctx = useEditorContext();

  /* ===== Sidebar state ===== */
  const [activeLeftTab, setActiveLeftTab] = useState("templates");
  const [activeRightTab, setActiveRightTab] = useState("attr");
  const [selectedShape, setSelectedShape] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [templateCat, setTemplateCat] = useState("全部");
  const [materialCat, setMaterialCat] = useState("全部");
  const [bgCat, setBgCat] = useState("全部");
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiSize, setAiSize] = useState("1:1");
  const [aiStyle, setAiStyle] = useState("写实");

  /* Backend data */
  const [backendTemplates, setBackendTemplates] = useState<BackendTemplate[]>([]);
  const [backendMaterials, setBackendMaterials] = useState<BackendMaterial[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [loadingMaterials, setLoadingMaterials] = useState(true);

  /* Gaoding templates */
  const [gaodingTemplates, setGaodingTemplates] = useState<TemplateMeta[]>([]);
  const [loadingGaoding, setLoadingGaoding] = useState(true);
  const [loadingTemplate, setLoadingTemplate] = useState(false);

  /* Canvas state (multi-canvas) */
  const [canvases, setCanvases] = useState<CanvasAttr[]>([
    { id: "c1", name: "画板 1", w: DEFAULT_CANVAS_W, h: DEFAULT_CANVAS_H, bgColor: "#e8edf5" },
  ]);
  const [activeCanvasId, setActiveCanvasId] = useState("c1");
  const activeCanvas = canvases.find(c => c.id === activeCanvasId) ?? canvases[0];
  const canvasW = activeCanvas?.w || DEFAULT_CANVAS_W;
  const canvasH = activeCanvas?.h || DEFAULT_CANVAS_H;

  /* Size modal */
  const [showSizeTemplateModal, setShowSizeTemplateModal] = useState(false);

  /* ===== Fabric Canvas Hook ===== */
  const viewportRef = useRef<HTMLDivElement>(null);
  const canvasWrapperRef = useRef<HTMLDivElement>(null);
  /** Increments on every template load to force re-fit even when dimensions don't change */
  const [templateLoadKey, setTemplateLoadKey] = useState(0);

  // CRITICAL: Force dimensions if somehow they became 0
  const safeW = canvasW > 0 ? canvasW : DEFAULT_CANVAS_W;
  const safeH = canvasH > 0 ? canvasH : DEFAULT_CANVAS_H;

  const canvasKey = useRef(`canvas-${Date.now()}`).current;

  const fabricHook = useFabricCanvas({
    width: safeW,
    height: safeH,
    background: activeCanvas.bg ?? activeCanvas.bgColor,
    containerRef: viewportRef,
    wrapperRef: canvasWrapperRef,
    onSelectionChange: () => {
      // Auto-switch right panel based on selection
    },
  });

  /* ===== Fetch backend data ===== */
  useEffect(() => {
    setLoadingTemplates(true);
    editorApi.getTemplates()
      .then(res => setBackendTemplates(res.data?.items ?? []))
      .catch(() => setBackendTemplates([]))
      .finally(() => setLoadingTemplates(false));

    setLoadingMaterials(true);
    editorApi.getMaterials(undefined, 1, 100)
      .then(res => setBackendMaterials(res.data?.items ?? []))
      .catch(() => setBackendMaterials([]))
      .finally(() => setLoadingMaterials(false));
  }, []);

  /* ===== Fetch gaoding templates ===== */
  useEffect(() => {
    setLoadingGaoding(true);
    getTemplateList()
      .then(list => {
        console.log('[Editor] Loaded gaoding templates:', list.length);
        // Sort by object_count descending for richer templates first
        list.sort((a, b) => ((a as any).object_count || 0) - ((b as any).object_count || 0)).reverse();
        setGaodingTemplates(list);
      })
      .catch(e => {
        console.error("[Editor] Failed to load gaoding templates:", e);
        setGaodingTemplates([]);
      })
      .finally(() => setLoadingGaoding(false));
  }, []);

  /* ===== Load a gaoding template — ALWAYS use runtime design.json conversion ===== */
  const handleLoadGaodingTemplate = useCallback(async (meta: TemplateMeta) => {
    if (!confirm(`使用模板 "${meta.title}"？当前编辑内容将被覆盖。`)) return;

    setLoadingTemplate(true);
    try {
      // Step 1: Fetch design.json
      const designUrl = `/templates/${meta.folder}/design.json`;
      const dres = await fetch(designUrl, { cache: 'no-store' });
      if (!dres.ok) throw new Error(`Failed to load design.json: ${dres.status}`);
      const designJson = await dres.json();

      // Step 2: Preprocess SVGs (replace {{colors[N]}} placeholders) — shared URL cache
      const svgCache: Record<string, string> = {};
      async function preprocessSvg(el: Record<string, unknown>): Promise<void> {
        const type = el.type as string;
        if (type === 'svg' && typeof el.url === 'string') {
          const originalUrl = el.url as string;
          const colors = (el.colors as string[]) || [];
          if (colors.length > 0) {
            if (svgCache[originalUrl]) {
              el.url = svgCache[originalUrl];
            } else {
              const filename = originalUrl.split('/').pop()?.split('?')[0];
              const localUrl = filename ? `/templates/${meta.folder}/images/${filename}` : originalUrl;
              try {
                const res = await fetch(localUrl, { cache: 'no-store' });
                if (res.ok) {
                  let svgText = await res.text();
                  for (let i = 0; i < colors.length; i++) {
                    const regex = new RegExp(`\\{\\{colors\\[${i}\\]\\}\\}`, 'g');
                    svgText = svgText.replace(regex, colors[i]);
                  }
                  const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgText)}`;
                  el.url = dataUrl;
                  svgCache[originalUrl] = dataUrl;
                }
              } catch { /* ignore */ }
            }
          }
        }
        if (Array.isArray(el.elements)) {
          for (const child of el.elements) await preprocessSvg(child as Record<string, unknown>);
        }
        if (Array.isArray(el.layouts)) {
          for (const item of el.layouts) await preprocessSvg(item as Record<string, unknown>);
        }
        if (Array.isArray(el.pages)) {
          for (const item of el.pages) await preprocessSvg(item as Record<string, unknown>);
        }
      }
      await preprocessSvg(designJson as Record<string, unknown>);

      // Step 3: Runtime conversion — design.json → Fabric JSON
      const { fabricJson, bgImageUrl } = gaodingToFabric(designJson as any, meta.folder);

      console.log(`[handleLoadGaodingTemplate] ${meta.folder}: ${fabricJson.objects.length} objects, canvas ${fabricJson.width}x${fabricJson.height}, bg: ${fabricJson.background}`);

      const cw = fabricJson.width || DEFAULT_CANVAS_W;
      const ch = fabricJson.height || DEFAULT_CANVAS_H;

      // Load content with background image
      fabricHook.loadFromJSON(JSON.stringify(fabricJson), bgImageUrl);

      // Use the fabric JSON background color if available
      const bgColor = typeof fabricJson.background === 'string' ? fabricJson.background : "#ffffff";

      // Update React state so wrapper div + status bar show correct dimensions
      setCanvases(prev => prev.map(c => c.id === "c1" ? { ...c, w: cw, h: ch, bgColor } : c));

      // Bump template load key to force re-fit via useEffect (even if dimensions didn't change)
      setTemplateLoadKey(k => k + 1);
    } catch (e) {
      console.error("Failed to load template:", e);
      alert("模板加载失败: " + (e as Error).message);
    } finally {
      setLoadingTemplate(false);
    }
  }, [fabricHook, ctx]);

  /* ===== Load template from sessionStorage (after canvas is ready) ===== */
  const templateLoadedRef = useRef(false);

  useEffect(() => {
    if (!fabricHook.isReady || templateLoadedRef.current) return;

    const tpl = sessionStorage.getItem("selectedTemplate");
    if (tpl) {
      templateLoadedRef.current = true;
      try {
        const data = JSON.parse(tpl);
        if (data.name) ctx.setProjectName(data.name);

        if (data.folder) {
          (async () => {
            const meta = await getTemplateMetaForFolder(data.folder);
            // Runtime conversion — design.json → Fabric JSON
            const designUrl = `/templates/${meta.folder}/design.json`;
            const dres = await fetch(designUrl, { cache: 'no-store' });
            if (!dres.ok) throw new Error(`Failed to load design.json: ${dres.status}`);
            const designJson = await dres.json();
            const svgCache: Record<string, string> = {};
            async function preprocessSvg(el: Record<string, unknown>): Promise<void> {
              const type = el.type as string;
              if (type === 'svg' && typeof el.url === 'string') {
                const originalUrl = el.url as string;
                const colors = (el.colors as string[]) || [];
                if (colors.length > 0) {
                  if (svgCache[originalUrl]) {
                    el.url = svgCache[originalUrl];
                  } else {
                    const filename = originalUrl.split('/').pop()?.split('?')[0];
                    const localUrl = filename ? `/templates/${meta.folder}/images/${filename}` : originalUrl;
                    try {
                      const res = await fetch(localUrl, { cache: 'no-store' });
                      if (res.ok) {
                        let svgText = await res.text();
                        for (let i = 0; i < colors.length; i++) {
                          const regex = new RegExp(`\\{\\{colors\\[${i}\\]\\}\\}`, 'g');
                          svgText = svgText.replace(regex, colors[i]);
                        }
                        const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgText)}`;
                        el.url = dataUrl;
                        svgCache[originalUrl] = dataUrl;
                      }
                    } catch { /* ignore */ }
                  }
                }
              }
              if (Array.isArray(el.elements)) for (const c of el.elements) await preprocessSvg(c as Record<string, unknown>);
              if (Array.isArray(el.layouts)) for (const c of el.layouts) await preprocessSvg(c as Record<string, unknown>);
              if (Array.isArray(el.pages)) for (const c of el.pages) await preprocessSvg(c as Record<string, unknown>);
            }
            await preprocessSvg(designJson as Record<string, unknown>);
            const { fabricJson, bgImageUrl } = gaodingToFabric(designJson as any, meta.folder);
            fabricHook.loadFromJSON(JSON.stringify(fabricJson), bgImageUrl);
            const bgColor = typeof fabricJson.background === 'string' ? fabricJson.background : "#ffffff";
            setCanvases(prev => prev.map(c => c.id === "c1" ? { ...c, w: fabricJson.width, h: fabricJson.height, bgColor } : c));
            setTemplateLoadKey(k => k + 1);
          })().catch(e => {
            console.error("Failed to load template:", e);
          });
        } else if (data.fabric_json) {
          // Legacy path: load content first, then resize
          fabricHook.loadFromJSON(data.fabric_json);
          if (data.width && data.height) {
            setCanvases(prev => prev.map(c => c.id === "c1" ? { ...c, w: data.width, h: data.height } : c));
          }
        }
      } catch (e) {
        console.error("Failed to load template:", e);
      } finally {
        sessionStorage.removeItem("selectedTemplate");
      }
    } else {
      // Try loading saved project — but don't block if backend is unavailable
      editorApi.getProjects(1, 1)
        .then(res => {
          if (res.data?.items?.length > 0) {
            const project = res.data.items[0];
            ctx.setProjectName(project.name);
            ctx.setProjectId(project.id);
            return editorApi.getProject(project.id);
          }
          return null;
        })
        .then(detailRes => {
          if (!detailRes?.data?.fabric_json) return;
          // Only load JSON, don't touch canvas dimensions
          fabricHook.loadFromJSON(detailRes.data.fabric_json);
        })
        .catch(() => {
          // Backend might not be running — this is OK
          console.log("[Editor] Backend not available, using blank canvas");
        });
    }
  }, [fabricHook.isReady]);

  /* ===== Sync canvas content to state after Fabric hook is ready and content loaded ===== */
  useEffect(() => {
    if (!fabricHook.isReady) return;

    const timer = setTimeout(() => {
      try {
        const json = fabricHook.toJSON();
        if (json) {
          setCanvases(prev => prev.map(c =>
            c.id === activeCanvasId ? { ...c, contentJson: json } : c
          ));
        }
      } catch (e) {
        console.warn('Failed to sync canvas content to state:', e);
      }
    }, 1500); // wait for async template loading to complete

    return () => clearTimeout(timer);
  }, [fabricHook.isReady, activeCanvasId]); // CRITICAL: don't include fabricHook object in deps — it changes every render

  /* ===== Sync undo/redo to context ===== */
  useEffect(() => {
    ctx._setCanUndo(fabricHook.canUndo);
    ctx._setCanRedo(fabricHook.canRedo);
  }, [fabricHook.canUndo, fabricHook.canRedo]);

  /* ===== Trigger viewport CSS when canvas dimensions change (e.g., after template load) ===== */
  useEffect(() => {
    if (!fabricHook.isReady) return;
    // Delay to allow React to re-render the wrapper div with new dimensions
    const timer = setTimeout(() => {
      fabricHook.fitViewportToContainer();
    }, 100);
    return () => clearTimeout(timer);
  }, [canvasW, canvasH, templateLoadKey]); // Re-fit when dimensions change OR template is loaded

  /* ===== Register undo/redo/save in context ===== */
  useEffect(() => {
    ctx._setUndoFn(fabricHook.undo);
    ctx._setRedoFn(fabricHook.redo);
    ctx._setSaveFn(async () => {
      ctx.setHasUnsavedChanges(false);
      ctx.setIsSaving(true);
      try {
        const json = fabricHook.toJSON();
        if (!json) return;
        if (ctx.projectId) {
          await editorApi.updateProject(ctx.projectId, {
            name: ctx.projectName,
            fabric_json: json,
            thumbnail: fabricHook.toDataURL("jpeg", 0.3),
          });
        } else {
          const res = await editorApi.createProject({
            name: ctx.projectName,
            fabric_json: json,
            thumbnail: fabricHook.toDataURL("jpeg", 0.3),
          });
          ctx.setProjectId(res.data.id);
        }
      } catch (e) {
        console.error("Save failed:", e);
        localStorage.setItem("editor_draft", JSON.stringify({
          canvases,
          activeCanvasId,
          fabric_json: fabricHook.toJSON(),
        }));
      } finally {
        ctx.setIsSaving(false);
      }
    });
  }, [fabricHook]);

  /* ===== Selection for property panel ===== */
  const [selectedEl, setSelectedEl] = useState<Record<string, any> | null>(null);
  useEffect(() => {
    const obj = fabricHook.selectedObject;
    if (!obj) {
      setSelectedEl(null);
      return;
    }
    setSelectedEl({
      type: obj.type,
      name: (obj as any).name || obj.type,
      left: Math.round(obj.left || 0),
      top: Math.round(obj.top || 0),
      width: Math.round((obj.width || 0) * (obj.scaleX || 1)),
      height: Math.round((obj.height || 0) * (obj.scaleY || 1)),
      angle: Math.round(obj.angle || 0),
      opacity: Math.round((obj.opacity ?? 1) * 100),
      fill: obj.fill as string | undefined,
      stroke: obj.stroke as string | undefined,
      strokeWidth: obj.strokeWidth || 0,
      text: obj.type?.includes("text") ? (obj as any).text : undefined,
      fontSize: (obj as any).fontSize,
      fontFamily: (obj as any).fontFamily,
      fontWeight: (obj as any).fontWeight,
      fontStyle: (obj as any).fontStyle,
      underline: (obj as any).underline,
      strikethrough: (obj as any).strikethrough,
      textAlign: (obj as any).textAlign,
      flipX: obj.flipX || false,
      flipY: obj.flipY || false,
      _fabricObject: obj,
    });
  }, [fabricHook.selectedObject, fabricHook.selectedIds.length]);

  /* ===== Element creation ===== */
  const makeShape = useCallback((shapeId: string) => {
    const cx = canvasW / 2 - 50;
    const cy = canvasH / 2 - 50;
    switch (shapeId) {
      case "rect": return fabricHook.addRect({ left: cx, top: cy });
      case "circle": return fabricHook.addCircle({ left: cx, top: cy });
      case "triangle": return fabricHook.addTriangle({ left: cx, top: cy });
      case "line": return fabricHook.addLine({ left: cx, top: cy });
      case "diamond":
        return fabricHook.addRect({ left: cx, top: cy, width: 100, height: 100, angle: 45, fill: "#6366f1", name: "菱形" });
      case "star":
      case "hexagon":
        return fabricHook.addRect({ left: cx, top: cy, fill: "#f59e0b", name: shapeId });
      case "arrow":
        return fabricHook.addRect({ left: cx, top: cy, width: 120, height: 30, fill: "#3b82f6", name: "箭头", rx: 4, ry: 4 });
      default: return fabricHook.addRect({ left: cx, top: cy });
    }
  }, [canvasW, canvasH, fabricHook]);

  /* ===== Update element property ===== */
  const updateProp = useCallback((key: string, value: any) => {
    const obj = fabricHook.selectedObject;
    if (!obj) return;
    (obj as any).set(key, value);
    fabricHook.fabricCanvas.current?.renderAll();
    setSelectedEl(prev => prev ? { ...prev, [key]: value } : null);
  }, [fabricHook]);

  /* ===== Layer list ===== */
  const layerList = fabricHook.getLayerList();
  const totalLayerCount = layerList.length;

  /* ===== Multi-canvas ===== */
  const switchToCanvas = useCallback((id: string) => {
    const c = canvases.find(x => x.id === id);
    if (!c) return;

    // Save current active canvas content before switching
    if (fabricHook.fabricCanvas.current && activeCanvasId !== id) {
      try {
        const json = fabricHook.toJSON();
        if (json) {
          setCanvases(prev => prev.map(x =>
            x.id === activeCanvasId ? { ...x, contentJson: json } : x
          ));
        }
      } catch (e) {
        console.warn('Failed to save canvas content before switch:', e);
      }
    }

    setActiveCanvasId(id);

    // Load target canvas content
    if (c.contentJson && fabricHook.isReady) {
      fabricHook.loadFromJSON(c.contentJson);
    }
  }, [canvases, activeCanvasId, fabricHook, fabricHook.isReady]);

  const addCanvas = useCallback(() => {
    const newId = `c${Date.now()}`;
    const colors = ["#e8edf5", "#fff3cd", "#d1fae5", "#ede9fe", "#fce7f3"];
    const newBg = colors[canvases.length % colors.length];
    setCanvases(prev => [...prev, { id: newId, name: `画板 ${prev.length + 1}`, w: DEFAULT_CANVAS_W, h: DEFAULT_CANVAS_H, bgColor: newBg }]);
    setActiveCanvasId(newId);
  }, [canvases.length]);

  const duplicateCanvas = useCallback((id: string) => {
    const src = canvases.find(c => c.id === id);
    if (!src) return;
    const newId = `c${Date.now()}`;
    setCanvases(prev => [...prev, { ...src, id: newId, name: src.name + " 副本", contentJson: id === activeCanvasId ? (fabricHook.toJSON() || src.contentJson) : src.contentJson }]);
    setActiveCanvasId(newId);
  }, [canvases, activeCanvasId, fabricHook]);

  const deleteCanvasFn = useCallback((id: string) => {
    if (canvases.length <= 1) return;
    const next = canvases.filter(c => c.id !== id);
    setCanvases(next);
    if (activeCanvasId === id) {
      setActiveCanvasId(next[0].id);
    }
  }, [canvases, activeCanvasId]);

  const resizeCanvas = useCallback((w: number, h: number) => {
    setCanvases(prev => prev.map(c => c.id === activeCanvasId ? { ...c, w, h } : c));
  }, [activeCanvasId]);

  /* ===== Export ===== */
  const handleExport = useCallback(() => {
    const dataUrl = fabricHook.toDataURL("png", 1);
    const link = document.createElement("a");
    link.download = `${ctx.projectName || "design"}.png`;
    link.href = dataUrl;
    link.click();
  }, [fabricHook, ctx.projectName]);

  /* ===== Filter backend data ===== */
  const templateCategoryMap: Record<string, string> = {
    poster: "海报", social: "社交媒体", card: "卡片", banner: "电商", presentation: "演示",
  };
  const materialCategoryMap: Record<string, string> = {
    decoration: "装饰", arrow: "箭头", shape: "形状", interface: "界面",
  };

  const filteredTemplates = backendTemplates.filter(t => {
    const catLabel = templateCategoryMap[t.category] || t.category;
    const matchCat = templateCat === "全部" || catLabel === templateCat;
    const matchSearch = t.name.toLowerCase().includes(searchQuery.toLowerCase());
    return matchCat && matchSearch;
  });

  const filteredMaterials = backendMaterials.filter(m => {
    const catLabel = materialCategoryMap[m.category] || m.category;
    const matchCat = materialCat === "全部" || catLabel === materialCat;
    const matchSearch = m.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (m.tags || []).some(tag => tag.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchCat && matchSearch;
  });

  /* ===== Render ===== */
  return (
    <div className="flex flex-col h-screen bg-background">
      {/* ===== TOP BAR ===== */}
      <div className="flex items-center justify-between border-b bg-card px-4" style={{ height: 48 }}>
        <div className="flex items-center gap-3">
          <Sparkles className="h-5 w-5 text-primary" />
          <span className="text-sm font-medium">{ctx.projectName}</span>
          {ctx.hasUnsavedChanges && <span className="text-[10px] text-muted-foreground">· 未保存</span>}
          {ctx.isSaving && <span className="text-[10px] text-primary">保存中...</span>}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={fabricHook.undo} disabled={!fabricHook.canUndo} className="p-1.5 rounded hover:bg-accent disabled:opacity-30" title="撤销">
            <Undo2 className="h-4 w-4" />
          </button>
          <button onClick={fabricHook.redo} disabled={!fabricHook.canRedo} className="p-1.5 rounded hover:bg-accent disabled:opacity-30" title="重做">
            <Redo2 className="h-4 w-4" />
          </button>
          <div className="h-4 w-px bg-border mx-1" />
          <button onClick={() => ctx.triggerSave()} className="p-1.5 rounded hover:bg-accent" title="保存">
            <Save className="h-4 w-4" />
          </button>
          <button onClick={handleExport} className="p-1.5 rounded hover:bg-accent" title="导出">
            <Download className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* ===== MAIN 3-PANEL AREA ===== */}
      <div className="flex flex-1 min-h-0">

        {/* ===== LEFT PANEL (280px) ===== */}
        <div className="flex w-72 shrink-0 flex-col border-r bg-card">
          {/* Horizontal tabs at TOP (like original) */}
          <div className="flex border-b bg-card shrink-0">
            {[
              { id: "templates", icon: LayoutGrid, label: "模板" },
              { id: "elements", icon: Square, label: "元素" },
              { id: "text", icon: Type, label: "文字" },
              { id: "materials", icon: ImageIcon, label: "素材" },
              { id: "backgrounds", icon: Palette, label: "背景" },
              { id: "layers", icon: Layers, label: "图层" },
              { id: "ai", icon: Wand2, label: "AI" },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => { setActiveLeftTab(tab.id); setSearchQuery(""); }}
                className={cn(
                  "flex-1 flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium transition-colors border-b-2",
                  activeLeftTab === tab.id ? "text-primary border-primary" : "text-muted-foreground border-transparent hover:text-foreground"
                )}
              >
                <tab.icon className="h-4 w-4" />
                {tab.label}
              </button>
            ))}
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-auto">

            {/* === Templates === */}
            {activeLeftTab === "templates" && (
              <div className="p-3">
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input type="text" placeholder="搜索模板..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="w-full rounded-lg border bg-background py-2 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
                </div>

                {/* Tabs: gaoding / backend */}
                <div className="flex gap-1.5 mb-3 flex-wrap">
                  <button
                    onClick={() => setTemplateCat("全部")}
                    className={cn("rounded-full px-2.5 py-1 text-xs transition-colors", templateCat === "全部" ? "bg-primary/10 text-primary font-medium" : "bg-muted hover:bg-primary/10 hover:text-primary")}
                  >
                    稿定模板 ({gaodingTemplates.length})
                  </button>
                  <button
                    onClick={() => setTemplateCat("后端")}
                    className={cn("rounded-full px-2.5 py-1 text-xs transition-colors", templateCat === "后端" ? "bg-primary/10 text-primary font-medium" : "bg-muted hover:bg-primary/10 hover:text-primary")}
                  >
                    后端模板 ({backendTemplates.length})
                  </button>
                </div>

                {/* Loading overlay */}
                {loadingTemplate && (
                  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
                    <div className="flex items-center gap-3 bg-white rounded-xl px-6 py-4 shadow-lg">
                      <Loader2 className="h-6 w-6 animate-spin text-primary" />
                      <span className="text-sm font-medium">加载模板中...</span>
                    </div>
                  </div>
                )}

                {/* Gaoding templates */}
                {templateCat !== "后端" && (
                  loadingGaoding ? (
                    <div className="flex items-center justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>
                  ) : (
                    <div className="grid grid-cols-2 gap-2.5">
                      {gaodingTemplates
                        .filter(t => t.title.toLowerCase().includes(searchQuery.toLowerCase()))
                        .map(t => {
                          return (
                            <button
                              key={t.id}
                              onClick={() => handleLoadGaodingTemplate(t)}
                              className="group flex flex-col overflow-hidden rounded-lg border bg-card shadow-sm transition-all hover:shadow-md hover:border-primary/30"
                            >
                              {/* Fixed-height preview, image fills with object-cover */}
                              <div className="relative overflow-hidden bg-gray-100" style={{ height: 120 }}>
                                <img
                                  src={t.preview.startsWith('/') ? t.preview : `/templates/${t.folder}/preview.png`}
                                  alt={t.title}
                                  className="w-full h-full object-cover"
                                  loading="lazy"
                                />
                                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors" />
                                <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                  <Plus className="h-4 w-4 text-white drop-shadow" />
                                </div>
                                <div className="absolute bottom-1 left-1 bg-black/50 text-white text-[9px] px-1 rounded">
                                  {t.width}×{t.height}
                                </div>
                              </div>
                              <div className="p-1.5">
                                <p className="truncate text-[10px] font-medium leading-tight">{t.title}</p>
                                <p className="text-[9px] text-muted-foreground mt-0.5">{t.image_count} 素材</p>
                              </div>
                            </button>
                          );
                        })}
                    </div>
                  )
                )}

                {/* Backend templates (when selected) */}
                {templateCat === "后端" && (
                  loadingTemplates ? (
                    <div className="flex items-center justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>
                  ) : filteredTemplates.length === 0 ? (
                    <div className="text-center py-8 text-sm text-muted-foreground">暂无模板</div>
                  ) : (
                    <div className="grid grid-cols-2 gap-2.5">
                      {filteredTemplates.map(t => {
                        let fabricW = DEFAULT_CANVAS_W, fabricH = DEFAULT_CANVAS_H;
                        try { const f = JSON.parse(t.fabric_json || "{}"); fabricW = f.width || DEFAULT_CANVAS_W; fabricH = f.height || DEFAULT_CANVAS_H; } catch {}
                        const bgColors: Record<string, string> = { poster: "#f59e0b", social: "#6366f1", card: "#8b5cf6", banner: "#ec4899", presentation: "#14b8a6" };
                        const color = bgColors[t.category] || "#6366f1";
                        return (
                          <button key={t.id} onClick={() => {
                            if (!confirm(`使用模板 "${t.name}"？当前编辑内容将被覆盖。`)) return;
                            ctx.setProjectName(t.name);
                            setCanvases(prev => prev.map(c2 => c2.id === "c1" ? { ...c2, w: fabricW, h: fabricH } : c2));
                            fabricHook.loadFromJSON(t.fabric_json || "{}");
                            setTemplateLoadKey(k => k + 1);
                          }} className="group flex flex-col overflow-hidden rounded-lg border bg-card shadow-sm transition-all hover:shadow-md hover:border-primary/30">
                            <div className="aspect-[4/3] flex items-center justify-center text-xs font-medium text-white relative" style={{ background: `linear-gradient(135deg, ${color}, ${color}88)` }}>
                              <div className="w-8 h-8 rounded bg-white/20" />
                              <div className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity"><Plus className="h-4 w-4 text-white" /></div>
                            </div>
                            <div className="p-2">
                              <p className="truncate text-xs font-medium">{t.name}</p>
                              <div className="mt-0.5 flex items-center justify-between">
                                <span className="text-[10px] text-muted-foreground">{templateCategoryMap[t.category] || t.category}</span>
                                <span className="text-[10px] text-muted-foreground">{fabricW}×{fabricH}</span>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  )
                )}
              </div>
            )}

            {/* === Elements === */}
            {activeLeftTab === "elements" && (
              <div className="p-3 space-y-4">
                <h4 className="text-sm font-medium">基本形状</h4>
                <div className="grid grid-cols-4 gap-2">
                  {elementShapes.map(el => (
                    <button key={el.id} onClick={() => { setSelectedShape(el.id); makeShape(el.id); }} className={cn("flex flex-col items-center gap-1.5 rounded-lg border py-3 transition-colors", selectedShape === el.id ? "border-primary bg-primary/5 text-primary" : "hover:bg-accent")}>
                      <el.icon className="h-5 w-5" /><span className="text-[10px]">{el.label}</span>
                    </button>
                  ))}
                </div>
                <h4 className="text-sm font-medium">媒体</h4>
                <div className="grid grid-cols-2 gap-2">
                  <button onClick={() => {
                    const input = document.createElement("input");
                    input.type = "file";
                    input.accept = "image/*";
                    input.onchange = (e) => {
                      const file = (e.target as HTMLInputElement).files?.[0];
                      if (!file) return;
                      const reader = new FileReader();
                      reader.onload = () => {
                        fabricHook.addImage(reader.result as string, { left: canvasW / 2 - 50, top: canvasH / 2 - 50 });
                      };
                      reader.readAsDataURL(file);
                    };
                    input.click();
                  }} className="flex flex-col items-center gap-1.5 rounded-lg border bg-card py-4 hover:bg-accent transition-colors">
                    <Image className="h-5 w-5 text-muted-foreground" /><span className="text-[10px]">上传图片</span>
                  </button>
                </div>
                <h4 className="text-sm font-medium">装饰元素</h4>
                {loadingMaterials ? (
                  <div className="flex items-center justify-center py-4"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
                ) : backendMaterials.length === 0 ? (
                  <div className="text-center py-4 text-xs text-muted-foreground">暂无素材</div>
                ) : (
                  <div className="grid grid-cols-4 gap-2">
                    {backendMaterials.slice(0, 8).map(m => (
                      <button key={m.id} onClick={() => {
                        fabricHook.addImage(m.url, { left: canvasW / 2 - (m.width || 50) / 2, top: canvasH / 2 - (m.height || 50) / 2, name: m.name });
                      }} className="flex flex-col items-center gap-1 rounded-lg border bg-card p-2 hover:bg-accent hover:shadow-sm transition-all">
                        {m.url ? (
                          <img src={m.url} alt={m.name} className="h-6 w-6 object-contain" />
                        ) : (
                          <Image className="h-6 w-6 text-muted-foreground" />
                        )}
                        <span className="text-[9px] truncate w-full text-center text-muted-foreground">{m.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* === Text === */}
            {activeLeftTab === "text" && (
              <div className="p-3 space-y-3">
                <button onClick={() => fabricHook.addText("双击编辑文字", { left: canvasW / 2 - 100, top: canvasH / 2 - 15 })} className="w-full rounded-lg border-2 border-dashed border-muted-foreground/40 py-5 text-center transition-colors hover:border-primary hover:bg-primary/5 group">
                  <Plus className="mx-auto mb-2 h-6 w-6 text-muted-foreground group-hover:text-primary" />
                  <span className="text-sm text-muted-foreground group-hover:text-primary">添加文本框</span>
                </button>
                <div>
                  <h4 className="mb-2 text-sm font-medium">预设文字样式</h4>
                  <div className="space-y-2">
                    {[
                      { nm: "主标题", sz: 36, fw: "bold", t: "主标题文字" },
                      { nm: "副标题", sz: 22, fw: "semibold", t: "副标题文字" },
                      { nm: "正文", sz: 14, fw: "normal", t: "正文内容，支持多行文本" },
                    ].map(p => (
                      <button key={p.nm} onClick={() => {
                        fabricHook.addText(p.t, { left: 60, top: 80, fontSize: p.sz, fontWeight: p.fw, name: p.nm });
                      }} className="w-full rounded-lg border bg-card p-4 text-left hover:bg-accent transition-colors">
                        <span style={{ fontSize: p.sz, fontWeight: p.fw as any }}>{p.nm}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <h4 className="mb-2 text-sm font-medium">艺术字</h4>
                  <div className="grid grid-cols-2 gap-2">
                    <button onClick={() => fabricHook.addText("渐变", { left: 100, top: 100, fontSize: 32, fontWeight: "black", fill: "#6366f1", textAlign: "center" })} className="rounded-lg border bg-card p-4 text-center hover:bg-accent transition-colors">
                      <span className="text-xl font-black bg-gradient-to-r from-primary to-purple-500 bg-clip-text text-transparent">渐变</span>
                    </button>
                    <button onClick={() => fabricHook.addText("间距", { left: 100, top: 100, fontSize: 20, fontWeight: "bold", fill: "#0f172a", textAlign: "center" })} className="rounded-lg border bg-card p-4 text-center hover:bg-accent transition-colors">
                      <span className="text-lg font-bold tracking-[0.3em]">间距</span>
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* === Materials === */}
            {activeLeftTab === "materials" && (
              <div className="p-3">
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input type="text" placeholder="搜索素材..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="w-full rounded-lg border bg-background py-2 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
                </div>
                <div className="flex gap-1.5 mb-3 flex-wrap">
                  {["全部", ...Array.from(new Set(filteredMaterials.map(m => materialCategoryMap[m.category] || m.category)))].map(c => (
                    <button key={c} onClick={() => setMaterialCat(c)} className={cn("rounded-full px-2.5 py-1 text-xs transition-colors", materialCat === c ? "bg-primary/10 text-primary font-medium" : "bg-muted hover:bg-primary/10 hover:text-primary")}>{c}</button>
                  ))}
                </div>
                {loadingMaterials ? (
                  <div className="flex items-center justify-center py-8"><Loader2 className="h-6 w-6 animate-spin text-primary" /></div>
                ) : filteredMaterials.length === 0 ? (
                  <div className="text-center py-8 text-sm text-muted-foreground">暂无素材</div>
                ) : (
                  <div className="grid grid-cols-3 gap-2">
                    {filteredMaterials.map(m => (
                      <button key={m.id} onClick={() => {
                        fabricHook.addImage(m.url, { left: canvasW / 2 - (m.width || 50) / 2, top: canvasH / 2 - (m.height || 50) / 2, name: m.name });
                      }} className="flex flex-col items-center gap-1.5 rounded-lg border bg-card p-3 hover:bg-accent hover:shadow-sm transition-all">
                        {m.url ? (
                          <img src={m.url} alt={m.name} className="w-10 h-10 object-contain" />
                        ) : (
                          <Image className="h-10 w-10 text-muted-foreground" />
                        )}
                        <span className="text-[10px] truncate w-full text-center">{m.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* === Backgrounds === */}
            {activeLeftTab === "backgrounds" && (
              <div className="p-3">
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input type="text" placeholder="搜索背景..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="w-full rounded-lg border bg-background py-2 pl-9 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30" />
                </div>
                <div className="flex gap-1.5 mb-3 flex-wrap">
                  {["全部", "纯色", "渐变", "图案"].map(c => (
                    <button key={c} onClick={() => setBgCat(c)} className={cn("rounded-full px-2.5 py-1 text-xs transition-colors", bgCat === c ? "bg-primary/10 text-primary font-medium" : "bg-muted hover:bg-primary/10 hover:text-primary")}>{c}</button>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {mockBackgrounds.filter(bg => {
                    if (bgCat === "全部") return true;
                    if (bgCat === "纯色") return bg.type === "color";
                    if (bgCat === "渐变") return bg.type === "gradient";
                    if (bgCat === "图案") return bg.type === "gradient" && bg.value.includes("repeating");
                    return true;
                  }).map(bg => (
                    <button
                      key={bg.id}
                      onClick={() => {
                        setCanvases(prev => prev.map(c2 => c2.id === activeCanvasId ? { ...c2, bgColor: bg.value, bg: bg.value } : c2));
                      }}
                      className={cn("flex flex-col overflow-hidden rounded-lg border transition-all hover:shadow-md",
                        (activeCanvas.bg ?? activeCanvas.bgColor) === bg.value ? "border-primary ring-1 ring-primary/20" : "hover:border-primary/30")}
                    >
                      <div className="aspect-[4/3]" style={{ background: bg.value }} />
                      <div className="px-2 py-1.5 bg-card">
                        <p className="truncate text-[10px] font-medium">{bg.name}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* === Layers === */}
            {activeLeftTab === "layers" && (
              <div>
                <div className="flex items-center justify-between px-3 py-2.5 border-b shrink-0">
                  <span className="text-sm font-medium">图层 ({totalLayerCount})</span>
                  <div className="flex items-center gap-0.5">
                    <button onClick={fabricHook.bringForward} className="p-1.5 rounded hover:bg-accent text-muted-foreground"><ArrowUp className="h-3.5 w-3.5" /></button>
                    <button onClick={fabricHook.sendBackward} className="p-1.5 rounded hover:bg-accent text-muted-foreground"><ArrowDown className="h-3.5 w-3.5" /></button>
                    <button onClick={fabricHook.cloneSelected} className="p-1.5 rounded hover:bg-accent text-muted-foreground"><Copy className="h-3.5 w-3.5" /></button>
                    <button onClick={fabricHook.deleteSelected} className="p-1.5 rounded hover:bg-red-50 text-destructive"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
                <div className="overflow-auto" style={{ maxHeight: "calc(100vh - 200px)" }}>
                  {layerList.map((layer: any) => {
                    const cfg = layerTypeConfig[layer.type] || { icon: "?", color: "bg-gray-100 text-gray-600" };
                    const isSelected = fabricHook.selectedIds.includes(layer.id);
                    return (
                      <div
                        key={layer.id}
                        onClick={() => fabricHook.selectObject(layer._object)}
                        className={cn("flex items-center gap-2 px-3 py-2 text-xs cursor-pointer transition-colors", isSelected ? "bg-primary/5 text-primary" : "hover:bg-accent")}
                      >
                        <span className={cn("w-5 h-5 rounded flex items-center justify-center text-[10px]", cfg.color)}>{cfg.icon}</span>
                        <span className="flex-1 truncate">{layer.name}</span>
                        <button onClick={(e) => { e.stopPropagation(); layer._object.set("visible", !layer.visible); fabricHook.fabricCanvas.current?.renderAll(); }} className={cn("p-0.5 rounded", layer.visible ? "text-muted-foreground" : "text-muted-foreground/30")}>
                          {layer.visible ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                        </button>
                        <button onClick={(e) => { e.stopPropagation(); layer._object.set("selectable", !layer._object.selectable); fabricHook.fabricCanvas.current?.renderAll(); }} className={cn("p-0.5 rounded", layer.locked ? "text-amber-500" : "text-muted-foreground/30")}>
                          {layer.locked ? <Lock className="h-3 w-3" /> : <Unlock className="h-3 w-3" />}
                        </button>
                      </div>
                    );
                  })}
                  {layerList.length === 0 && (
                    <div className="text-center py-8 text-xs text-muted-foreground">暂无图层</div>
                  )}
                </div>
              </div>
            )}

            {/* === AI === */}
            {activeLeftTab === "ai" && (
              <div className="p-3 space-y-3">
                <h4 className="text-sm font-medium">AI 生成图片</h4>
                <textarea value={aiPrompt} onChange={e => setAiPrompt(e.target.value)} placeholder="描述你想要的图片..." className="w-full rounded-lg border bg-background p-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none h-20" />
                <div>
                  <label className="text-sm font-medium mb-1.5 block">图片尺寸</label>
                  <div className="grid grid-cols-3 gap-1.5">
                    {["1:1", "16:9", "9:16", "4:3", "3:4", "3:2"].map(r => (
                      <button key={r} onClick={() => setAiSize(r)} className={cn("rounded-md border py-1.5 text-xs font-medium hover:bg-accent transition-colors", aiSize === r ? "border-primary bg-primary/5 text-primary" : "")}>{r}</button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="text-sm font-medium mb-1.5 block">风格</label>
                  <div className="grid grid-cols-4 gap-1.5">
                    {["写实", "插画", "3D", "动漫", "水彩", "像素", "油画", "极简"].map(s => (
                      <button key={s} onClick={() => setAiStyle(s)} className={cn("rounded-md border py-1.5 text-xs hover:bg-accent transition-colors", aiStyle === s ? "border-primary bg-primary/5 text-primary" : "")}>{s}</button>
                    ))}
                  </div>
                </div>
                <button className="w-full rounded-lg bg-primary py-2.5 text-sm font-medium text-white shadow-sm flex items-center justify-center gap-2"><Sparkles className="h-4 w-4" />生成图片</button>
              </div>
            )}
          </div>
        </div>

        {/* ===== CENTER CANVAS ===== */}
        <div className="flex flex-1 flex-col min-w-0 bg-gray-100/60">
          <div
            ref={viewportRef}
            className="flex-1 overflow-auto flex items-center justify-center p-6"
            onClick={e => { if (e.target === e.currentTarget) fabricHook.deselectAll(); }}
          >
            {/* Canvas + labels */}
            <div className="flex flex-col items-center gap-6">
              {canvases.map(c => {
                const isActive = c.id === activeCanvasId;

                return (
                  <div key={c.id} className="flex flex-col items-center gap-2">
                    <div className="flex items-center gap-2">
                      <span className={cn("text-xs font-medium px-2 py-0.5 rounded", isActive ? "bg-primary/10 text-primary" : "text-muted-foreground")}>{c.name}</span>
                      <span className="text-[10px] text-muted-foreground font-mono">{c.w} × {c.h}</span>
                    </div>
                    <div
                      ref={isActive ? canvasWrapperRef : undefined}
                      className={cn("relative rounded-sm transition-all bg-white overflow-hidden", isActive ? "ring-2 ring-primary ring-offset-2" : "opacity-90 hover:opacity-100 cursor-pointer border shadow-md")}
                      style={isActive ? {} : { width: Math.min(c.w * 0.15, 120), height: Math.min(c.h * 0.15, 100) }}
                      onClick={e => { e.stopPropagation(); if (!isActive) switchToCanvas(c.id); }}
                    >
                      {/* Active canvas: Fabric.js controls CSS dimensions via applyCanvasViewportCss */}
                      {isActive ? (
                        <canvas key={canvasKey} ref={fabricHook.canvasEl}
                          style={{ display: 'block', background: activeCanvas.bg ?? activeCanvas.bgColor, boxShadow: '0 8px 32px rgba(99,102,241,0.15), 0 2px 8px rgba(0,0,0,0.08)' }} />
                      ) : (
                        /* Inactive canvas: simple preview with background color */
                        <div style={{ width: '100%', height: '100%', background: c.bg ?? c.bgColor }} className="flex items-center justify-center">
                          <span className="text-xs text-muted-foreground">点击切换</span>
                        </div>
                      )}
                      {/* Overlay for inactive: click hint */}
                      {!isActive && (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/0 hover:bg-black/10 transition-colors rounded-sm">
                          <span className="text-xs font-medium text-white drop-shadow-md bg-black/30 px-2 py-1 rounded opacity-0 hover:opacity-100 transition-opacity">点击切换</span>
                        </div>
                      )}
                    </div>
                    {isActive && (
                      <div className="flex items-center gap-0.5">
                        <button onClick={(e) => { e.stopPropagation(); duplicateCanvas(c.id); }} className="p-0.5 rounded hover:bg-accent text-muted-foreground" title="复制"><Copy className="h-2.5 w-2.5" /></button>
                        <button onClick={(e) => { e.stopPropagation(); deleteCanvasFn(c.id); }} className="p-0.5 rounded hover:bg-red-50 text-destructive" title="删除" disabled={canvases.length <= 1}><Trash2 className="h-2.5 w-2.5" /></button>
                      </div>
                    )}
                  </div>
                );
              })}
              {/* Add canvas button */}
              <button onClick={addCanvas} className="flex items-center gap-2 rounded-lg border-2 border-dashed border-muted-foreground/40 px-6 py-3 text-sm text-muted-foreground hover:border-primary hover:text-primary transition-colors">
                <Plus className="h-4 w-4" />添加画板
              </button>
            </div>
          </div>

          {/* Status bar：缩放 + 适应视口/1:1 必须可见，窄屏时换行 */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1.5 border-t bg-card px-3 py-2 shrink-0 min-h-9 text-xs text-muted-foreground">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 min-w-0">
              <span className="tabular-nums">{safeW} × {safeH}px</span>
              {fabricHook.selectedIds.length > 0 && <span>已选 {fabricHook.selectedIds.length} 个</span>}
              <span>图层 {totalLayerCount}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => fabricHook.setZoom(z => Math.max(25, z - 10))} className="hover:text-foreground p-0.5 rounded" aria-label="缩小"><ZoomOut className="h-4 w-4" /></button>
                <input type="range" min={25} max={200} value={fabricHook.zoomPercent} onChange={e => fabricHook.setZoom(Number(e.target.value))} className="w-24 sm:w-28 accent-primary" />
                <button type="button" onClick={() => fabricHook.setZoom(z => Math.min(200, z + 10))} className="hover:text-foreground p-0.5 rounded" aria-label="放大"><ZoomIn className="h-4 w-4" /></button>
                <span className="w-9 text-right font-mono text-foreground">{fabricHook.zoomPercent}%</span>
              </div>
              <div className="h-4 w-px bg-border hidden sm:block" />
              <button
                type="button"
                onClick={() => fabricHook.fitViewportToContainer()}
                className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-1 text-foreground hover:bg-accent"
                title="整图画布缩放到当前可见区域，一眼看全"
              >
                <Maximize2 className="h-3.5 w-3.5 shrink-0" />
                <span>适应</span>
              </button>
              <button
                type="button"
                onClick={() => fabricHook.setViewportPixelPerfect()}
                className="rounded border border-border px-2 py-1 text-foreground hover:bg-accent"
                title="按 1:1 像素显示（图很大时可滚动）"
              >
                1:1
              </button>
            </div>
          </div>
        </div>

        {/* ===== RIGHT PANEL (280px) ===== */}
        <div className="flex w-72 shrink-0 flex-col border-l bg-card overflow-y-auto">

          {/* === 画板 section (always visible) === */}
          <div className="border-b px-3 py-2.5 shrink-0 flex items-center justify-between">
            <h3 className="text-sm font-medium">画板</h3>
            <button onClick={addCanvas} className="flex items-center gap-1 rounded-md bg-primary/10 text-primary px-2 py-1 text-xs font-medium hover:bg-primary/20 transition-colors">
              <Plus className="h-3 w-3" />添加画板
            </button>
          </div>

          {/* Canvas list */}
          <div className="px-3 py-2 border-b shrink-0">
            <div className="flex gap-2 overflow-x-auto pb-1">
              {canvases.map(c => {
                const isActive = c.id === activeCanvasId;
                return (
                  <div key={c.id} className={cn("flex flex-col items-center gap-1 rounded-lg border p-1.5 cursor-pointer transition-all min-w-[72px]", isActive ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "hover:border-border")}>
                    <div onClick={() => switchToCanvas(c.id)} className="w-12 h-8 rounded-sm shadow-sm flex items-center justify-center" style={{ background: c.bg ?? c.bgColor }}>
                      <span className="text-[8px] text-muted-foreground">{c.w > 0 ? Math.round((c.w / c.h) * 10) / 10 : ""}</span>
                    </div>
                    <span className="text-[10px] truncate w-full text-center">{c.name}</span>
                    {isActive && (
                      <div className="flex items-center gap-0.5">
                        <button onClick={(e) => { e.stopPropagation(); duplicateCanvas(c.id); }} className="p-0.5 rounded hover:bg-accent text-muted-foreground" title="复制"><Copy className="h-2.5 w-2.5" /></button>
                        <button onClick={(e) => { e.stopPropagation(); deleteCanvasFn(c.id); }} className="p-0.5 rounded hover:bg-red-50 text-destructive" title="删除" disabled={canvases.length <= 1}><Trash2 className="h-2.5 w-2.5" /></button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* === Canvas properties — when NO element selected === */}
          {!selectedEl && (
            <>
              <div className="px-3 py-3 border-b shrink-0">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold">画板属性</span>
                  <span className="text-[10px] text-muted-foreground font-mono">{activeCanvas.w} × {activeCanvas.h} px</span>
                </div>
                {/* Canvas preview */}
                <div className="flex items-center justify-center rounded-lg border bg-muted/30 p-3 mb-3">
                  <div className="rounded-sm shadow-sm border" style={{ width: Math.min(120, (activeCanvas.w / activeCanvas.h) * 75), height: Math.min(75, (activeCanvas.h / activeCanvas.w) * 120), background: activeCanvas.bg ?? activeCanvas.bgColor }} />
                </div>
                {/* Size buttons */}
                <div className="grid grid-cols-2 gap-1.5 mb-3">
                  <button onClick={() => {
                    const w = prompt("宽度 (px)", String(activeCanvas.w));
                    const h = prompt("高度 (px)", String(activeCanvas.h));
                    if (w && h) resizeCanvas(parseInt(w), parseInt(h));
                  }} className="flex items-center justify-center gap-1 rounded-md border bg-background py-1.5 text-xs hover:bg-accent transition-colors">
                    <Crop className="h-3.5 w-3.5" />调整尺寸
                  </button>
                  <button onClick={() => setShowSizeTemplateModal(!showSizeTemplateModal)} className="flex items-center justify-center gap-1 rounded-md border bg-background py-1.5 text-xs hover:bg-accent transition-colors">
                    <LayoutGrid className="h-3.5 w-3.5" />尺寸模板
                  </button>
                </div>
                {/* Size templates popup */}
                {showSizeTemplateModal && (
                  <div className="mb-3 rounded-lg border bg-background p-2 max-h-40 overflow-auto">
                    {presetSizes.map(ps => (
                      <button key={ps.name} onClick={() => { resizeCanvas(ps.w, ps.h); setShowSizeTemplateModal(false); }} className="w-full flex items-center justify-between px-2 py-1.5 text-xs hover:bg-accent rounded transition-colors">
                        <span>{ps.name}</span>
                        <span className="text-muted-foreground">{ps.w}×{ps.h} ({ps.ratio})</span>
                      </button>
                    ))}
                  </div>
                )}
                {/* Background color */}
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-muted-foreground shrink-0">背景色</span>
                  <input type="color" value={activeCanvas.bgColor.startsWith("#") ? activeCanvas.bgColor : "#ffffff"} onChange={e => { const v = e.target.value; setCanvases(prev => prev.map(c2 => c2.id === activeCanvasId ? { ...c2, bgColor: v, bg: v } : c2)); }} className="h-6 w-6 rounded cursor-pointer border-0 shrink-0" />
                  <div className="flex items-center gap-1 flex-1">
                    {["#ffffff", "#f8fafc", "#0f172a", "#6366f1", "#ec4899", "#10b981"].map(c => (
                      <button key={c} onClick={() => setCanvases(prev => prev.map(c2 => c2.id === activeCanvasId ? { ...c2, bgColor: c, bg: c } : c2))} className={cn("h-5 w-5 rounded-sm border transition-all", (activeCanvas.bg ?? activeCanvas.bgColor) === c ? "ring-2 ring-primary ring-offset-1 scale-110" : "hover:scale-110")} style={{ backgroundColor: c }} />
                    ))}
                  </div>
                </div>
                {/* Background image upload */}
                <div className="mt-2 flex gap-2">
                  <button onClick={() => {
                    const input = document.createElement("input");
                    input.type = "file";
                    input.accept = "image/*";
                    input.onchange = (e) => {
                      const file = (e.target as HTMLInputElement).files?.[0];
                      if (!file) return;
                      const reader = new FileReader();
                      reader.onload = () => {
                        setCanvases(prev => prev.map(c2 => c2.id === activeCanvasId ? { ...c2, bgImage: reader.result as string } : c2));
                      };
                      reader.readAsDataURL(file);
                    };
                    input.click();
                  }} className="flex-1 flex items-center justify-center gap-1 rounded-md border bg-background py-1.5 text-xs hover:bg-accent transition-colors">
                    <Image className="h-3.5 w-3.5" />上传图片
                  </button>
                  <button onClick={() => setActiveLeftTab("backgrounds")} className="flex-1 flex items-center justify-center gap-1 rounded-md border bg-background py-1.5 text-xs hover:bg-accent transition-colors">
                    <Palette className="h-3.5 w-3.5" />背景模板
                  </button>
                </div>
              </div>
              <div className="px-3 py-3">
                <p className="text-xs text-muted-foreground">点击画布中的元素即可编辑属性</p>
              </div>
            </>
          )}

          {/* === Element properties (when element selected) === */}
          {selectedEl && (
            <>
              <div className="border-b px-3 py-2.5 flex items-center justify-between shrink-0">
                <div className="flex items-center gap-2">
                  <span className={cn("flex h-6 w-6 items-center justify-center rounded text-xs font-bold", layerTypeConfig[selectedEl.type]?.color)}>
                    {layerTypeConfig[selectedEl.type]?.icon}
                  </span>
                  <input type="text" value={selectedEl.name} onChange={e => updateProp("name", e.target.value)} className="text-sm font-semibold bg-transparent border-b border-transparent focus:border-primary/50 focus:outline-none rounded px-0.5 w-28" />
                </div>
                <div className="flex items-center gap-0.5">
                  <button onClick={fabricHook.cloneSelected} className="p-1.5 rounded hover:bg-accent text-muted-foreground" title="复制"><Copy className="h-3.5 w-3.5" /></button>
                  <button onClick={() => updateProp("selectable", !(selectedEl._fabricObject as any)?.selectable)} className={cn("p-1.5 rounded hover:bg-accent", !selectedEl._fabricObject?.selectable ? "text-amber-500" : "text-muted-foreground")} title="锁定">
                    {!selectedEl._fabricObject?.selectable ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
                  </button>
                  <button onClick={fabricHook.deleteSelected} className="p-1.5 rounded hover:bg-red-50 text-destructive" title="删除"><Trash2 className="h-3.5 w-3.5" /></button>
                </div>
              </div>

              {/* Right panel tabs */}
              <div className="flex border-b shrink-0">
                <button onClick={() => setActiveRightTab("attr")} className={cn("flex-1 py-1.5 text-xs font-medium border-b-2 transition-colors", activeRightTab === "attr" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}>属性</button>
                <button onClick={() => setActiveRightTab("style")} className={cn("flex-1 py-1.5 text-xs font-medium border-b-2 transition-colors", activeRightTab === "style" ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}>样式</button>
              </div>

              {activeRightTab === "attr" && (
                <div className="p-3 space-y-4">
                  {/* Position */}
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-2">位置</h4>
                    <div className="grid grid-cols-2 gap-2">
                      <div><label className="text-[10px] text-muted-foreground">X</label><input type="number" value={selectedEl.left} onChange={e => updateProp("left", Number(e.target.value))} className="w-full rounded border bg-background px-2 py-1 text-xs" /></div>
                      <div><label className="text-[10px] text-muted-foreground">Y</label><input type="number" value={selectedEl.top} onChange={e => updateProp("top", Number(e.target.value))} className="w-full rounded border bg-background px-2 py-1 text-xs" /></div>
                    </div>
                  </div>
                  {/* Size */}
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-2">尺寸</h4>
                    <div className="grid grid-cols-2 gap-2">
                      <div><label className="text-[10px] text-muted-foreground">宽</label><input type="number" value={selectedEl.width} onChange={e => { const obj = selectedEl._fabricObject; if (!obj) return; const scaleX = Number(e.target.value) / (obj.width || 1); obj.scale(scaleX); fabricHook.fabricCanvas.current?.renderAll(); }} className="w-full rounded border bg-background px-2 py-1 text-xs" /></div>
                      <div><label className="text-[10px] text-muted-foreground">高</label><input type="number" value={selectedEl.height} onChange={e => { const obj = selectedEl._fabricObject; if (!obj) return; const scaleY = Number(e.target.value) / (obj.height || 1); obj.scale(scaleY); fabricHook.fabricCanvas.current?.renderAll(); }} className="w-full rounded border bg-background px-2 py-1 text-xs" /></div>
                    </div>
                  </div>
                  {/* Angle */}
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-2">旋转</h4>
                    <div className="flex items-center gap-2">
                      <input type="range" min={0} max={360} value={selectedEl.angle} onChange={e => updateProp("angle", Number(e.target.value))} className="flex-1 accent-primary" />
                      <span className="text-xs w-8 text-right">{selectedEl.angle}°</span>
                    </div>
                  </div>
                  {/* Opacity */}
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-2">透明度</h4>
                    <div className="flex items-center gap-2">
                      <input type="range" min={0} max={100} value={selectedEl.opacity} onChange={e => updateProp("opacity", Number(e.target.value) / 100)} className="flex-1 accent-primary" />
                      <span className="text-xs w-8 text-right">{selectedEl.opacity}%</span>
                    </div>
                  </div>
                  {/* Quick actions */}
                  <div className="flex gap-2 pt-2 border-t">
                    <button onClick={fabricHook.cloneSelected} className="flex-1 p-2 rounded border text-xs hover:bg-accent transition-colors flex items-center justify-center gap-1"><Copy className="h-3 w-3" />复制</button>
                    <button onClick={fabricHook.bringToFront} className="flex-1 p-2 rounded border text-xs hover:bg-accent transition-colors flex items-center justify-center gap-1"><ArrowUp className="h-3 w-3" />置顶</button>
                    <button onClick={fabricHook.sendToBack} className="flex-1 p-2 rounded border text-xs hover:bg-accent transition-colors flex items-center justify-center gap-1"><ArrowDown className="h-3 w-3" />置底</button>
                  </div>
                </div>
              )}

              {activeRightTab === "style" && (
                <div className="p-3 space-y-4">
                  {/* Fill Color */}
                  {selectedEl.fill && typeof selectedEl.fill === "string" && selectedEl.fill.startsWith("#") && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-2">填充颜色</h4>
                      <div className="flex flex-wrap gap-1.5">
                        {shapeDefaultColors.map(c => (
                          <button key={c} onClick={() => updateProp("fill", c)} className={cn("h-6 w-6 rounded-sm border transition-all", selectedEl.fill === c ? "ring-2 ring-primary scale-110" : "hover:scale-110")} style={{ backgroundColor: c }} />
                        ))}
                        <input type="color" value={selectedEl.fill} onChange={e => updateProp("fill", e.target.value)} className="h-6 w-8 rounded cursor-pointer border-0" />
                      </div>
                    </div>
                  )}
                  {/* Stroke */}
                  <div>
                    <h4 className="text-xs font-medium text-muted-foreground mb-2">描边</h4>
                    <div className="flex items-center gap-2">
                      <input type="color" value={selectedEl.stroke && typeof selectedEl.stroke === "string" ? selectedEl.stroke : "#000000"} onChange={e => updateProp("stroke", e.target.value)} className="h-6 w-8 rounded cursor-pointer border" />
                      <input type="number" min={0} max={20} value={selectedEl.strokeWidth || 0} onChange={e => updateProp("strokeWidth", Number(e.target.value))} className="w-16 rounded border bg-background px-2 py-1 text-xs" />
                      <span className="text-[10px] text-muted-foreground">px</span>
                    </div>
                  </div>
                  {/* Text-specific */}
                  {selectedEl.type?.includes("text") && (
                    <>
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">字体</h4>
                        <select value={selectedEl.fontFamily || "PingFang SC"} onChange={e => updateProp("fontFamily", e.target.value)} className="w-full rounded border bg-background px-2 py-1 text-xs">
                          <option value="PingFang SC">PingFang SC</option>
                          <option value="Microsoft YaHei">Microsoft YaHei</option>
                          <option value="Arial">Arial</option>
                          <option value="Helvetica">Helvetica</option>
                          <option value="Georgia">Georgia</option>
                        </select>
                      </div>
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">字号</h4>
                        <input type="number" value={selectedEl.fontSize || 24} onChange={e => updateProp("fontSize", Number(e.target.value))} className="w-full rounded border bg-background px-2 py-1 text-xs" />
                      </div>
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">对齐</h4>
                        <div className="flex gap-1">
                          {[{ v: "left", i: AlignLeft }, { v: "center", i: AlignCenter }, { v: "right", i: AlignRight }].map(a => (
                            <button key={a.v} onClick={() => updateProp("textAlign", a.v)} className={cn("flex-1 p-1.5 rounded border transition-colors", selectedEl.textAlign === a.v ? "bg-primary/10 border-primary text-primary" : "hover:bg-accent")}><a.i className="h-4 w-4" /></button>
                          ))}
                        </div>
                      </div>
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">样式</h4>
                        <div className="flex gap-1">
                          <button onClick={() => updateProp("fontWeight", selectedEl.fontWeight === "bold" ? "normal" : "bold")} className={cn("flex-1 p-1.5 rounded border transition-colors", selectedEl.fontWeight === "bold" && "bg-primary/10 border-primary text-primary")}><Bold className="h-4 w-4" /></button>
                          <button onClick={() => updateProp("fontStyle", selectedEl.fontStyle === "italic" ? "normal" : "italic")} className={cn("flex-1 p-1.5 rounded border transition-colors", selectedEl.fontStyle === "italic" && "bg-primary/10 border-primary text-primary")}><Italic className="h-4 w-4" /></button>
                          <button onClick={() => updateProp("underline", !selectedEl.underline)} className={cn("flex-1 p-1.5 rounded border transition-colors", selectedEl.underline && "bg-primary/10 border-primary text-primary")}><Underline className="h-4 w-4" /></button>
                        </div>
                      </div>
                      <div>
                        <h4 className="text-xs font-medium text-muted-foreground mb-2">文字颜色</h4>
                        <div className="flex flex-wrap gap-1.5">
                          {textColors.map(c => (
                            <button key={c} onClick={() => updateProp("fill", c)} className={cn("h-6 w-6 rounded-sm border transition-all", selectedEl.fill === c ? "ring-2 ring-primary scale-110" : "hover:scale-110")} style={{ backgroundColor: c }} />
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                  {/* Image-specific */}
                  {selectedEl.type === "image" && (
                    <div>
                      <h4 className="text-xs font-medium text-muted-foreground mb-2">翻转</h4>
                      <div className="flex gap-2">
                        <button onClick={() => updateProp("flipX", !selectedEl.flipX)} className={cn("flex-1 p-2 rounded border text-xs transition-colors", selectedEl.flipX && "bg-primary/10 border-primary text-primary")}><FlipHorizontal className="h-4 w-4 inline mr-1" />水平</button>
                        <button onClick={() => updateProp("flipY", !selectedEl.flipY)} className={cn("flex-1 p-2 rounded border text-xs transition-colors", selectedEl.flipY && "bg-primary/10 border-primary text-primary")}><FlipVertical className="h-4 w-4 inline mr-1" />垂直</button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
