/*
 * nwngps_gl.dll - draws the GPS panel inside Neverwinter Nights: EE.
 *
 * Loaded into nwmain.exe at runtime by nwngps/ingame.py (no game files change).
 * It swaps one pointer in nwmain's import table (GDI32!SwapBuffers) for our hook.
 * Each frame the hook copies the latest panel image that Python wrote into the
 * shared memory "nwngps_overlay" onto the screen with a textured quad, saving
 * and restoring all OpenGL state it touches, then calls the real SwapBuffers.
 *
 * Keyboard (v2): the game window is subclassed. Ctrl+Shift+G toggles the panel,
 * Ctrl+Shift+F opens the destination picker; while it is open every key goes to
 * the picker (events in the shared-memory ring) and none reaches the game.
 *
 * Unload: Python sets FLAG_UNLOAD; the hook frees its GL objects, puts the
 * original pointers back and the DLL frees itself. If Python stops updating for
 * 3 s the panel is hidden (so a crashed controller never leaves stale output).
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <GL/gl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* ---- shared memory layout v2 (keep in sync with nwngps/ingame.py) ---- */
#define DLL_VERSION 2u
#define SHM_NAME L"nwngps_overlay_v2"
#define SHM_MAGIC 0x5350474Eu /* 'NGPS' */
#define MAX_W 640
#define MAX_H 1024
#define HDR_SIZE 2048
#define SHM_SIZE (HDR_SIZE + MAX_W * MAX_H * 4)
#define FLAG_VISIBLE 1u
#define FLAG_UNLOAD 2u
#define GPS_EV_RING 64

/* events DLL -> Python */
#define EV_TOGGLE 1u   /* Ctrl+Shift+G */
#define EV_OPEN 2u     /* Ctrl+Shift+F: picker opened, keys are now captured */
#define EV_CHAR 3u     /* code = UTF-16 unit typed while capturing */
#define EV_KEY 4u      /* code = virtual key (Up/Down/Enter/Esc/Backspace...) while capturing */

typedef struct { uint32_t type, code, mods, pad; } ShmEvent;

typedef struct {
    uint32_t magic, version;
    volatile uint32_t seq;     /* seqlock: odd while Python writes */
    uint32_t width, height;
    int32_t off_x, off_y;      /* margins from the anchor corner, pixels */
    uint32_t anchor;           /* 0 = top-right, 1 = top-left */
    volatile uint32_t flags;
    volatile uint32_t dll_state; /* 0 unloaded, 1 attached, 2 hooked, 3 drawing, 9 error */
    volatile uint32_t dll_frames;
    volatile uint32_t view_w, view_h;
    volatile uint32_t dll_version;
    volatile uint32_t capturing;  /* 1 while the picker owns the keyboard */
    volatile uint32_t ev_head;    /* total events written; slot = head % GPS_EV_RING */
    char msg[128];
    ShmEvent events[GPS_EV_RING];     /* at offset 192 */
} ShmHeader;

/* ---- GL constants / function pointers beyond GL 1.1 ---- */
#define GL_CLAMP_TO_EDGE 0x812F
#define GL_TEXTURE0 0x84C0
#define GL_ACTIVE_TEXTURE 0x84E0
#define GL_CURRENT_PROGRAM 0x8B8D
#define GL_VERTEX_ARRAY_BINDING 0x85B5
#define GL_ARRAY_BUFFER_BINDING 0x8894
#define GL_DRAW_FRAMEBUFFER_BINDING 0x8CA6
#define GL_DRAW_FRAMEBUFFER 0x8CA9
#define GL_PIXEL_UNPACK_BUFFER 0x88EC
#define GL_PIXEL_UNPACK_BUFFER_BINDING 0x88EF
#define GL_UNPACK_ROW_LENGTH 0x0CF2
#define GL_SAMPLER_BINDING 0x8919
#define GL_FRAMEBUFFER_SRGB 0x8DB9
#define GL_BLEND_SRC_RGB 0x80C9
#define GL_BLEND_DST_RGB 0x80C8
#define GL_BLEND_SRC_ALPHA 0x80CB
#define GL_BLEND_DST_ALPHA 0x80CA
#define GL_BLEND_EQUATION_RGB 0x8009
#define GL_BLEND_EQUATION_ALPHA 0x883D
#define GL_FUNC_ADD 0x8006
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAGMENT_SHADER 0x8B30
#define GL_COMPILE_STATUS 0x8B81
#define GL_LINK_STATUS 0x8B82

typedef char GLchar;
typedef GLuint (APIENTRY *PFN_CreateShader)(GLenum);
typedef void (APIENTRY *PFN_ShaderSource)(GLuint, GLsizei, const GLchar *const *, const GLint *);
typedef void (APIENTRY *PFN_CompileShader)(GLuint);
typedef void (APIENTRY *PFN_GetShaderiv)(GLuint, GLenum, GLint *);
typedef void (APIENTRY *PFN_GetShaderInfoLog)(GLuint, GLsizei, GLsizei *, GLchar *);
typedef GLuint (APIENTRY *PFN_CreateProgram)(void);
typedef void (APIENTRY *PFN_AttachShader)(GLuint, GLuint);
typedef void (APIENTRY *PFN_LinkProgram)(GLuint);
typedef void (APIENTRY *PFN_GetProgramiv)(GLuint, GLenum, GLint *);
typedef void (APIENTRY *PFN_UseProgram)(GLuint);
typedef void (APIENTRY *PFN_DeleteShader)(GLuint);
typedef void (APIENTRY *PFN_DeleteProgram)(GLuint);
typedef GLint (APIENTRY *PFN_GetUniformLocation)(GLuint, const GLchar *);
typedef void (APIENTRY *PFN_Uniform1i)(GLint, GLint);
typedef void (APIENTRY *PFN_Uniform4f)(GLint, GLfloat, GLfloat, GLfloat, GLfloat);
typedef void (APIENTRY *PFN_GenVertexArrays)(GLsizei, GLuint *);
typedef void (APIENTRY *PFN_BindVertexArray)(GLuint);
typedef void (APIENTRY *PFN_DeleteVertexArrays)(GLsizei, const GLuint *);
typedef void (APIENTRY *PFN_BindBuffer)(GLenum, GLuint);
typedef void (APIENTRY *PFN_ActiveTexture)(GLenum);
typedef void (APIENTRY *PFN_BindFramebuffer)(GLenum, GLuint);
typedef void (APIENTRY *PFN_BlendFuncSeparate)(GLenum, GLenum, GLenum, GLenum);
typedef void (APIENTRY *PFN_BlendEquationSeparate)(GLenum, GLenum);
typedef void (APIENTRY *PFN_BindSampler)(GLuint, GLuint);

static struct {
    PFN_CreateShader CreateShader; PFN_ShaderSource ShaderSource; PFN_CompileShader CompileShader;
    PFN_GetShaderiv GetShaderiv; PFN_GetShaderInfoLog GetShaderInfoLog; PFN_CreateProgram CreateProgram;
    PFN_AttachShader AttachShader; PFN_LinkProgram LinkProgram; PFN_GetProgramiv GetProgramiv;
    PFN_UseProgram UseProgram; PFN_DeleteShader DeleteShader; PFN_DeleteProgram DeleteProgram;
    PFN_GetUniformLocation GetUniformLocation; PFN_Uniform1i Uniform1i; PFN_Uniform4f Uniform4f;
    PFN_GenVertexArrays GenVertexArrays; PFN_BindVertexArray BindVertexArray;
    PFN_DeleteVertexArrays DeleteVertexArrays; PFN_BindBuffer BindBuffer; PFN_ActiveTexture ActiveTexture;
    PFN_BindFramebuffer BindFramebuffer; PFN_BlendFuncSeparate BlendFuncSeparate;
    PFN_BlendEquationSeparate BlendEquationSeparate; PFN_BindSampler BindSampler; /* may be NULL */
} gl;

/* ---- module state ---- */
typedef BOOL (WINAPI *PFN_SwapBuffers)(HDC);
static HMODULE g_self;
static PFN_SwapBuffers g_real_swap;
static void **g_iat_slot;
static HANDLE g_map;
static ShmHeader *g_shm;
static uint8_t *g_pixels;           /* local copy, MAX_W*MAX_H*4 */
static uint32_t g_seen_seq = 0, g_tex_w = 0, g_tex_h = 0;
static ULONGLONG g_last_update = 0;
static int g_gl_ready = 0, g_gl_failed = 0, g_unloading = 0;
static GLuint g_prog, g_vao, g_tex;
static GLint g_u_rect, g_u_tex;

static void set_msg(const char *m) {
    if (g_shm) { strncpy_s(g_shm->msg, sizeof g_shm->msg, m, _TRUNCATE); }
}

#define LOAD(name) (*(PROC *)&gl.name = wglGetProcAddress("gl" #name))
static int load_gl(void) {
    LOAD(CreateShader); LOAD(ShaderSource); LOAD(CompileShader); LOAD(GetShaderiv); LOAD(GetShaderInfoLog);
    LOAD(CreateProgram); LOAD(AttachShader); LOAD(LinkProgram); LOAD(GetProgramiv); LOAD(UseProgram);
    LOAD(DeleteShader); LOAD(DeleteProgram); LOAD(GetUniformLocation); LOAD(Uniform1i); LOAD(Uniform4f);
    LOAD(GenVertexArrays); LOAD(BindVertexArray); LOAD(DeleteVertexArrays); LOAD(BindBuffer);
    LOAD(ActiveTexture); LOAD(BindFramebuffer); LOAD(BlendFuncSeparate); LOAD(BlendEquationSeparate);
    LOAD(BindSampler);
    return gl.CreateShader && gl.ShaderSource && gl.CompileShader && gl.GetShaderiv && gl.CreateProgram &&
           gl.AttachShader && gl.LinkProgram && gl.GetProgramiv && gl.UseProgram && gl.GetUniformLocation &&
           gl.Uniform1i && gl.Uniform4f && gl.GenVertexArrays && gl.BindVertexArray && gl.BindBuffer &&
           gl.ActiveTexture && gl.BindFramebuffer && gl.BlendFuncSeparate && gl.BlendEquationSeparate &&
           gl.DeleteVertexArrays && gl.DeleteProgram && gl.DeleteShader;
}

/* The quad's corners come from gl_VertexID, so no vertex buffers are needed. */
static const char *VS =
    "#version 150\n"
    "uniform vec4 uRect;\n"                   /* x0, yTop, x1, yBottom in NDC */
    "out vec2 vUV;\n"
    "void main(){ vec2 c = vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1));\n"
    "  vUV = c; gl_Position = vec4(mix(uRect.x, uRect.z, c.x), mix(uRect.y, uRect.w, c.y), 0.0, 1.0); }\n";
static const char *FS =
    "#version 150\n"
    "uniform sampler2D uTex; in vec2 vUV; out vec4 oColor;\n"
    "void main(){ oColor = texture(uTex, vUV); }\n";

static GLuint compile(GLenum type, const char *src) {
    GLuint s = gl.CreateShader(type);
    GLint ok = 0;
    gl.ShaderSource(s, 1, &src, NULL);
    gl.CompileShader(s);
    gl.GetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[120] = "shader: ";
        if (gl.GetShaderInfoLog) gl.GetShaderInfoLog(s, 110, NULL, log + 8);
        set_msg(log);
        gl.DeleteShader(s);
        return 0;
    }
    return s;
}

static int init_gl(void) {
    GLuint vs, fs;
    GLint ok = 0, prev_tex = 0;
    if (!load_gl()) { set_msg("missing GL 3.x functions"); return 0; }
    vs = compile(GL_VERTEX_SHADER, VS);
    fs = compile(GL_FRAGMENT_SHADER, FS);
    if (!vs || !fs) return 0;
    g_prog = gl.CreateProgram();
    gl.AttachShader(g_prog, vs);
    gl.AttachShader(g_prog, fs);
    gl.LinkProgram(g_prog);
    gl.DeleteShader(vs);
    gl.DeleteShader(fs);
    gl.GetProgramiv(g_prog, GL_LINK_STATUS, &ok);
    if (!ok) { set_msg("program link failed"); return 0; }
    g_u_rect = gl.GetUniformLocation(g_prog, "uRect");
    g_u_tex = gl.GetUniformLocation(g_prog, "uTex");
    gl.GenVertexArrays(1, &g_vao);
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &prev_tex);
    glGenTextures(1, &g_tex);
    glBindTexture(GL_TEXTURE_2D, g_tex);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, prev_tex);
    return 1;
}

static void free_gl(void) {
    if (!g_gl_ready) return;
    if (g_tex) glDeleteTextures(1, &g_tex);
    if (g_vao) gl.DeleteVertexArrays(1, &g_vao);
    if (g_prog) gl.DeleteProgram(g_prog);
    g_tex = g_vao = g_prog = 0;
    g_gl_ready = 0;
}

static int open_shm(void) {
    if (g_shm) return 1;
    g_map = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, SHM_NAME);
    if (!g_map) return 0;
    g_shm = (ShmHeader *)MapViewOfFile(g_map, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, SHM_SIZE);
    if (!g_shm || g_shm->magic != SHM_MAGIC) {
        if (g_shm) UnmapViewOfFile(g_shm);
        CloseHandle(g_map);
        g_shm = NULL; g_map = NULL;
        return 0;
    }
    return 1;
}

/* Copy a consistent frame (seqlock) into g_pixels; returns 1 if a new one was taken. */
static int take_frame(uint32_t *w, uint32_t *h) {
    uint32_t s1 = g_shm->seq, s2;
    if (s1 & 1 || s1 == g_seen_seq) return 0;
    MemoryBarrier();
    *w = g_shm->width; *h = g_shm->height;
    if (*w == 0 || *h == 0 || *w > MAX_W || *h > MAX_H) return 0;
    memcpy(g_pixels, (uint8_t *)g_shm + HDR_SIZE, (size_t)(*w) * (*h) * 4);
    MemoryBarrier();
    s2 = g_shm->seq;
    if (s1 != s2) return 0;
    g_seen_seq = s1;
    return 1;
}

static void draw_panel(HDC hdc) {
    GLint prog, vao, active_tex, tex2d, sampler = 0, fbo, vp[4], unpack_buf, unpack_align, unpack_row;
    GLint bsrc_rgb, bdst_rgb, bsrc_a, bdst_a, beq_rgb, beq_a;
    GLboolean blend, depth, cull, scissor, stencil, srgb, mask[4];
    RECT rc;
    uint32_t w, h, fw = 0, fh = 0;
    int vw, vh, x, y;
    HWND wnd = WindowFromDC(hdc);
    ULONGLONG now = GetTickCount64();

    if (!wnd || !GetClientRect(wnd, &rc)) return;
    vw = rc.right - rc.left; vh = rc.bottom - rc.top;
    g_shm->view_w = vw; g_shm->view_h = vh;
    if (vw <= 0 || vh <= 0) return;

    if (!g_gl_ready) {
        if (g_gl_failed) return;
        if (!init_gl()) { g_gl_failed = 1; g_shm->dll_state = 9; return; }
        g_gl_ready = 1;
    }

    /* ---- save state ---- */
    glGetIntegerv(GL_CURRENT_PROGRAM, &prog);
    glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
    glGetIntegerv(GL_ACTIVE_TEXTURE, &active_tex);
    gl.ActiveTexture(GL_TEXTURE0);
    glGetIntegerv(GL_TEXTURE_BINDING_2D, &tex2d);
    if (gl.BindSampler) glGetIntegerv(GL_SAMPLER_BINDING, &sampler);
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &fbo);
    glGetIntegerv(GL_VIEWPORT, vp);
    glGetIntegerv(GL_PIXEL_UNPACK_BUFFER_BINDING, &unpack_buf);
    glGetIntegerv(GL_UNPACK_ALIGNMENT, &unpack_align);
    glGetIntegerv(GL_UNPACK_ROW_LENGTH, &unpack_row);
    glGetIntegerv(GL_BLEND_SRC_RGB, &bsrc_rgb); glGetIntegerv(GL_BLEND_DST_RGB, &bdst_rgb);
    glGetIntegerv(GL_BLEND_SRC_ALPHA, &bsrc_a); glGetIntegerv(GL_BLEND_DST_ALPHA, &bdst_a);
    glGetIntegerv(GL_BLEND_EQUATION_RGB, &beq_rgb); glGetIntegerv(GL_BLEND_EQUATION_ALPHA, &beq_a);
    glGetBooleanv(GL_COLOR_WRITEMASK, mask);
    blend = glIsEnabled(GL_BLEND); depth = glIsEnabled(GL_DEPTH_TEST); cull = glIsEnabled(GL_CULL_FACE);
    scissor = glIsEnabled(GL_SCISSOR_TEST); stencil = glIsEnabled(GL_STENCIL_TEST);
    srgb = glIsEnabled(GL_FRAMEBUFFER_SRGB);

    /* ---- upload a new frame if Python published one ---- */
    glBindTexture(GL_TEXTURE_2D, g_tex);
    gl.BindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
    if (take_frame(&fw, &fh)) {
        if (fw != g_tex_w || fh != g_tex_h) {
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, fw, fh, 0, GL_RGBA, GL_UNSIGNED_BYTE, g_pixels);
            g_tex_w = fw; g_tex_h = fh;
        } else {
            glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, fw, fh, GL_RGBA, GL_UNSIGNED_BYTE, g_pixels);
        }
        g_last_update = now;
    }

    /* ---- draw (only if visible and Python is alive) ---- */
    w = g_tex_w; h = g_tex_h;
    if (w && h && (g_shm->flags & FLAG_VISIBLE) && now - g_last_update < 3000) {
        x = g_shm->anchor == 1 ? g_shm->off_x : vw - (int)w - g_shm->off_x;
        y = g_shm->off_y;
        gl.BindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
        glViewport(0, 0, vw, vh);
        glDisable(GL_DEPTH_TEST); glDisable(GL_CULL_FACE); glDisable(GL_SCISSOR_TEST);
        glDisable(GL_STENCIL_TEST); glDisable(GL_FRAMEBUFFER_SRGB);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glEnable(GL_BLEND);
        gl.BlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD);
        gl.BlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        if (gl.BindSampler) gl.BindSampler(0, 0);
        gl.UseProgram(g_prog);
        gl.Uniform1i(g_u_tex, 0);
        gl.Uniform4f(g_u_rect,
                     2.0f * x / vw - 1.0f, 1.0f - 2.0f * y / vh,
                     2.0f * (x + (int)w) / vw - 1.0f, 1.0f - 2.0f * (y + (int)h) / vh);
        gl.BindVertexArray(g_vao);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        g_shm->dll_state = 3;
    }

    /* ---- restore state ---- */
    gl.BindVertexArray(vao);
    gl.UseProgram(prog);
    if (gl.BindSampler) gl.BindSampler(0, sampler);
    glBindTexture(GL_TEXTURE_2D, tex2d);
    gl.ActiveTexture(active_tex);
    gl.BindFramebuffer(GL_DRAW_FRAMEBUFFER, fbo);
    glViewport(vp[0], vp[1], vp[2], vp[3]);
    gl.BindBuffer(GL_PIXEL_UNPACK_BUFFER, unpack_buf);
    glPixelStorei(GL_UNPACK_ALIGNMENT, unpack_align);
    glPixelStorei(GL_UNPACK_ROW_LENGTH, unpack_row);
    gl.BlendEquationSeparate(beq_rgb, beq_a);
    gl.BlendFuncSeparate(bsrc_rgb, bdst_rgb, bsrc_a, bdst_a);
    glColorMask(mask[0], mask[1], mask[2], mask[3]);
    (blend ? glEnable : glDisable)(GL_BLEND);
    (depth ? glEnable : glDisable)(GL_DEPTH_TEST);
    (cull ? glEnable : glDisable)(GL_CULL_FACE);
    (scissor ? glEnable : glDisable)(GL_SCISSOR_TEST);
    (stencil ? glEnable : glDisable)(GL_STENCIL_TEST);
    (srgb ? glEnable : glDisable)(GL_FRAMEBUFFER_SRGB);
}

/* ---- IAT hook ---- */
static void **find_iat_slot(HMODULE mod, const char *dll, const char *func) {
    uint8_t *base = (uint8_t *)mod;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress);
    for (; d->Name; d++) {
        IMAGE_THUNK_DATA *names, *iat;
        if (_stricmp((char *)(base + d->Name), dll) != 0 || !d->OriginalFirstThunk) continue;
        names = (IMAGE_THUNK_DATA *)(base + d->OriginalFirstThunk);
        iat = (IMAGE_THUNK_DATA *)(base + d->FirstThunk);
        for (; names->u1.AddressOfData; names++, iat++) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            if (strcmp((char *)((IMAGE_IMPORT_BY_NAME *)(base + names->u1.AddressOfData))->Name, func) == 0)
                return (void **)&iat->u1.Function;
        }
    }
    return NULL;
}

static void patch_slot(void **slot, void *value) {
    DWORD old;
    VirtualProtect(slot, sizeof(void *), PAGE_READWRITE, &old);
    InterlockedExchangePointer(slot, value);
    VirtualProtect(slot, sizeof(void *), old, &old);
}

/* ---- keyboard: window subclass for hotkeys and the picker ---- */
static HWND g_wnd;
static WNDPROC g_orig_wndproc;
static volatile LONG g_capturing = 0;
static int g_swallow_char = 0;   /* eat the WM_CHAR that follows a swallowed Enter/Esc/hotkey */

static void push_event(uint32_t type, uint32_t code) {
    ShmEvent *e;
    uint32_t mods = (GetKeyState(VK_SHIFT) < 0 ? 1u : 0u) | (GetKeyState(VK_CONTROL) < 0 ? 2u : 0u);
    if (!g_shm) return;
    e = &g_shm->events[g_shm->ev_head % GPS_EV_RING];
    e->type = type; e->code = code; e->mods = mods;
    MemoryBarrier();
    g_shm->ev_head++;
}

static void set_capture(int on) {
    g_capturing = on;
    if (g_shm) g_shm->capturing = (uint32_t)on;
}

static LRESULT CALLBACK hooked_wndproc(HWND h, UINT msg, WPARAM wp, LPARAM lp) {
    if (!g_unloading && g_shm) {
        int ctrl = GetKeyState(VK_CONTROL) < 0, shift = GetKeyState(VK_SHIFT) < 0;
        switch (msg) {
        case WM_KEYDOWN:
        case WM_SYSKEYDOWN:
            if (ctrl && shift && wp == 'G') { push_event(EV_TOGGLE, 0); g_swallow_char = 1; return 0; }
            if (ctrl && shift && wp == 'F') {
                if (!g_capturing) { set_capture(1); push_event(EV_OPEN, 0); }
                g_swallow_char = 1;
                return 0;
            }
            if (g_capturing) {
                if (wp == VK_RETURN || wp == VK_ESCAPE) {
                    push_event(EV_KEY, (uint32_t)wp);
                    set_capture(0);
                    g_swallow_char = 1;
                } else if (wp == VK_UP || wp == VK_DOWN || wp == VK_BACK || wp == VK_DELETE ||
                           wp == VK_PRIOR || wp == VK_NEXT || wp == VK_TAB || wp == VK_HOME || wp == VK_END) {
                    push_event(EV_KEY, (uint32_t)wp);
                }
                return 0;   /* the game never sees keys while the picker is open */
            }
            break;
        case WM_CHAR:
        case WM_SYSCHAR:
            if (g_swallow_char) { g_swallow_char = 0; if (wp < 32) return 0; }
            if (g_capturing) {
                if (wp >= 32 && wp != 127) push_event(EV_CHAR, (uint32_t)wp);
                return 0;
            }
            break;
        case WM_KEYUP:
        case WM_SYSKEYUP:
            if (g_capturing) return 0;
            break;
        case WM_KILLFOCUS:
            if (g_capturing) { push_event(EV_KEY, VK_ESCAPE); set_capture(0); }  /* alt-tab closes the picker */
            break;
        }
    }
    return CallWindowProcW(g_orig_wndproc, h, msg, wp, lp);
}

static void install_wndproc(HDC hdc) {
    HWND w = WindowFromDC(hdc);
    if (!w || g_wnd) return;
    g_orig_wndproc = (WNDPROC)SetWindowLongPtrW(w, GWLP_WNDPROC, (LONG_PTR)hooked_wndproc);
    if (g_orig_wndproc) g_wnd = w;
}

/* Returns 1 if our window procedure is out of the chain (safe to free the DLL). */
static int remove_wndproc(void) {
    if (!g_wnd) return 1;
    if ((WNDPROC)GetWindowLongPtrW(g_wnd, GWLP_WNDPROC) != hooked_wndproc) return 0;  /* someone chained after us */
    SetWindowLongPtrW(g_wnd, GWLP_WNDPROC, (LONG_PTR)g_orig_wndproc);
    g_wnd = NULL;
    return 1;
}

static DWORD WINAPI unload_thread(LPVOID p) {
    (void)p;
    Sleep(500); /* let any in-flight hook call return */
    FreeLibraryAndExitThread(g_self, 0);
}

static BOOL WINAPI hooked_swap(HDC hdc) {
    if (!g_unloading && (g_shm || open_shm())) {
        g_shm->dll_frames++;
        g_shm->dll_version = DLL_VERSION;
        if (!g_wnd) install_wndproc(hdc);
        if (g_shm->flags & FLAG_UNLOAD) {
            int can_free;
            g_unloading = 1;
            set_capture(0);
            free_gl();
            patch_slot(g_iat_slot, (void *)g_real_swap);
            can_free = remove_wndproc();
            g_shm->dll_state = 0;
            set_msg(can_free ? "unloaded" : "unhooked; staying loaded (window procedure chained)");
            UnmapViewOfFile(g_shm); CloseHandle(g_map);
            g_shm = NULL; g_map = NULL;
            if (can_free) CloseHandle(CreateThread(NULL, 0, unload_thread, NULL, 0, NULL));
        } else {
            __try { draw_panel(hdc); }
            __except (EXCEPTION_EXECUTE_HANDLER) { g_gl_failed = 1; set_msg("exception while drawing"); }
        }
    }
    return g_real_swap(hdc);
}

static DWORD WINAPI init_thread(LPVOID p) {
    (void)p;
    g_pixels = (uint8_t *)VirtualAlloc(NULL, MAX_W * MAX_H * 4, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    g_iat_slot = find_iat_slot(GetModuleHandleW(NULL), "GDI32.dll", "SwapBuffers");
    if (open_shm()) g_shm->dll_state = 1;
    if (!g_iat_slot || !g_pixels) {
        set_msg("SwapBuffers import not found");
        if (g_shm) g_shm->dll_state = 9;
        return 0;
    }
    g_real_swap = (PFN_SwapBuffers)*g_iat_slot;
    patch_slot(g_iat_slot, (void *)hooked_swap);
    if (g_shm) { g_shm->dll_state = 2; set_msg("hooked"); }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_self = inst;
        DisableThreadLibraryCalls(inst);
        CloseHandle(CreateThread(NULL, 0, init_thread, NULL, 0, NULL));
    } else if (reason == DLL_PROCESS_DETACH && reserved == NULL) {
        /* FreeLibrary without the unload handshake: make sure the game never calls into freed code */
        if (g_iat_slot && g_real_swap && *g_iat_slot == (void *)hooked_swap) patch_slot(g_iat_slot, (void *)g_real_swap);
        remove_wndproc();
        if (g_pixels) VirtualFree(g_pixels, 0, MEM_RELEASE);
    }
    return TRUE;
}
