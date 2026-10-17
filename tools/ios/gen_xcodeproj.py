#!/usr/bin/env python3
"""gen_xcodeproj: write an Xcode project for Pentamoor on an iPad (docs/notes/ios.md, "On a real iPad").

    python3 tools/ios/gen_xcodeproj.py [--team TEAMID] [--bundle-id org.example.pentamoor] [--entitlements] [--out dist/ios/xcode]
    open dist/ios/xcode/Pentamoor.xcodeproj

No generator, no CocoaPods, nothing to install: this writes the project file itself (Xcode's old-style text format) from the runtime's own source list (`make -C src/port print-ios-src`).
The project has two targets:

  GameLibs    an aggregate target with one build step, `tools/ios/build_ios.sh <simulator|device> libs`: SDL2 (the pinned source, built static) and the three game modules (the C lifted from
              YOUR game files, joined into one object per program with only its entry point visible). It needs sources/generated (tools/lift/lift_all.sh) and is incremental.
  Pentamoor   the app: the runtime's C files compiled by Xcode, linked with those objects, SDL2 and the system frameworks. It depends on GameLibs.

Signing is yours to set: pick your team in Xcode (Signing & Capabilities), or pass --team. Nothing here touches the keychain or any provisioning profile. The result holds code made from your
own game files and is for your own devices only: dist/ is git-ignored, and a built app is never to be committed or given to anyone.
"""
import argparse
import hashlib
import os
import plistlib
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

MIN_IOS = "15.0"
LINK_SDK = "26.0"               # the SDK version the app says it was built with (build_ios.sh, "The scene life cycle" in docs/notes/ios.md)
PROGRAMS = ("magic", "deck", "duel")
FRAMEWORKS = ("UIKit", "Foundation", "CoreGraphics", "QuartzCore", "Metal", "OpenGLES", "AudioToolbox", "AVFoundation", "CoreAudio", "CoreMotion", "CoreHaptics", "GameController",
              "CoreBluetooth", "ImageIO", "UniformTypeIdentifiers")


def uid(name):
    """A 24-hex-digit object id, the same for the same name every time."""
    return hashlib.md5(name.encode()).hexdigest()[:24].upper()


def q(s):
    """A string as the project file spells it: quoted unless it is plain."""
    if re.fullmatch(r"[A-Za-z0-9_./]+", s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def qlist(items, indent):
    pad = "\t" * (indent + 1)
    return "(\n" + "".join("%s%s,\n" % (pad, q(i)) for i in items) + "\t" * indent + ")"


def runtime_sources():
    """The runtime's C files for iOS: the Makefile's own list (IOS_SRC), so the project cannot drift from `make ios-runtime`."""
    out = subprocess.run(["make", "-s", "-C", os.path.join(ROOT, "src", "port"), "print-ios-src"], capture_output=True, text=True)
    if out.returncode != 0 or not out.stdout.split():
        raise SystemExit("gen_xcodeproj: `make -C src/port print-ios-src` failed:\n" + out.stderr)
    return out.stdout.split()


def info_plist(path_out):
    """Info.plist for the project: tools/ios/Info.plist.in's keys, with Xcode's build settings where the script has its own values."""
    body = open(os.path.join(HERE, "Info.plist.in")).read()
    body = body.replace("@BUNDLE_ID@", "$(PRODUCT_BUNDLE_IDENTIFIER)").replace("@MIN@", "$(IPHONEOS_DEPLOYMENT_TARGET)")
    body = re.sub(r"\t<key>CFBundleSupportedPlatforms</key>\n\t<array>\n\t\t<string>@PLATFORM@</string>\n\t</array>\n", "", body)   # Xcode writes that one itself
    body = re.sub(r"\t<key>UIDeviceFamily</key>\n\t<array>\n\t\t<integer>2</integer>\n\t</array>\n", "", body)           # TARGETED_DEVICE_FAMILY says it
    body = body.replace("<string>Pentamoor</string>\n\t<key>CFBundleIdentifier", "<string>$(EXECUTABLE_NAME)</string>\n\t<key>CFBundleIdentifier", 1)
    text = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n' + body + '</dict>\n</plist>\n')
    plistlib.loads(text.encode())                       # it must parse
    with open(path_out, "w") as f:
        f.write(text)


GAMELIBS_SCRIPT = r'''set -e
case "$PLATFORM_NAME" in
  iphonesimulator) P=simulator ;;
  iphoneos) P=device ;;
  *) echo "Pentamoor: unsupported platform $PLATFORM_NAME"; exit 1 ;;
esac
# a clean environment: Xcode's own build variables must not reach the xcodebuild that builds SDL2 inside
exec env -i HOME="$HOME" USER="$USER" TMPDIR="$TMPDIR" DEVELOPER_DIR="$DEVELOPER_DIR" PATH="/usr/bin:/bin:/usr/sbin:/sbin:$DEVELOPER_DIR/usr/bin" IOS_MIN="$IPHONEOS_DEPLOYMENT_TARGET" IOS_LINK_SDK="%(link)s" sh "%(root)s/tools/ios/build_ios.sh" "$P" libs
'''


def build(team, bundle_id, entitlements, out_dir):
    srcs = runtime_sources()
    os.makedirs(out_dir, exist_ok=True)
    plist_path = os.path.join(out_dir, "Info.plist")
    info_plist(plist_path)
    ent_path = os.path.join(HERE, "Pentamoor.entitlements")

    objs = []                   # (id, text) in the order written, by section
    sections = {k: [] for k in ("PBXAggregateTarget", "PBXBuildFile", "PBXContainerItemProxy", "PBXFileReference", "PBXFrameworksBuildPhase", "PBXGroup", "PBXNativeTarget", "PBXProject",
                                "PBXShellScriptBuildPhase", "PBXSourcesBuildPhase", "PBXTargetDependency", "XCBuildConfiguration", "XCConfigurationList")}

    def add(kind, oid, comment, body):
        sections[kind].append("\t\t%s /* %s */ = %s;\n" % (oid, comment, body))

    # files
    file_ids, build_ids = [], []
    for s in srcs:
        fr, bf = uid("file:" + s), uid("build:" + s)
        add("PBXFileReference", fr, s, '{isa = PBXFileReference; lastKnownFileType = sourcecode.c.c; name = %s; path = %s; sourceTree = "<absolute>"; }' % (q(s), q(os.path.join(ROOT, "src", "port", s))))
        add("PBXBuildFile", bf, s + " in Sources", "{isa = PBXBuildFile; fileRef = %s; }" % fr)
        file_ids.append(fr)
        build_ids.append(bf)
    plist_ref, ent_ref, product_ref = uid("file:Info.plist"), uid("file:entitlements"), uid("product")
    add("PBXFileReference", plist_ref, "Info.plist", '{isa = PBXFileReference; lastKnownFileType = text.plist.xml; name = Info.plist; path = %s; sourceTree = "<absolute>"; }' % q(plist_path))
    add("PBXFileReference", ent_ref, "Pentamoor.entitlements", '{isa = PBXFileReference; lastKnownFileType = text.plist.entitlements; name = Pentamoor.entitlements; path = %s; sourceTree = "<absolute>"; }' % q(ent_path))
    add("PBXFileReference", product_ref, "Pentamoor.app", "{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = Pentamoor.app; sourceTree = BUILT_PRODUCTS_DIR; }")

    # groups
    g_main, g_src, g_res, g_prod = uid("g:main"), uid("g:src"), uid("g:res"), uid("g:products")
    add("PBXGroup", g_src, "Runtime", "{isa = PBXGroup; children = %s; name = Runtime; sourceTree = \"<group>\"; }" % qlist(file_ids, 3))
    add("PBXGroup", g_res, "Support", "{isa = PBXGroup; children = %s; name = Support; sourceTree = \"<group>\"; }" % qlist([plist_ref, ent_ref], 3))
    add("PBXGroup", g_prod, "Products", "{isa = PBXGroup; children = %s; name = Products; sourceTree = \"<group>\"; }" % qlist([product_ref], 3))
    add("PBXGroup", g_main, "", "{isa = PBXGroup; children = %s; sourceTree = \"<group>\"; }" % qlist([g_src, g_res, g_prod], 3))

    # targets
    t_libs, t_app, proj = uid("t:GameLibs"), uid("t:Pentamoor"), uid("project")
    script = uid("script")
    add("PBXShellScriptBuildPhase", script, "Build SDL2 and the game modules",
        "{isa = PBXShellScriptBuildPhase; alwaysOutOfDate = 1; buildActionMask = 2147483647; files = (); inputFileListPaths = (); inputPaths = (); name = %s; outputFileListPaths = (); outputPaths = (); "
        "runOnlyForDeploymentPostprocessing = 0; shellPath = /bin/sh; shellScript = %s; showEnvVarsInLog = 0; }" % (q("Build SDL2 and the game modules"), q(GAMELIBS_SCRIPT % {"root": ROOT, "link": LINK_SDK})))
    cl_libs, cl_app, cl_proj = uid("cl:libs"), uid("cl:app"), uid("cl:proj")
    add("PBXAggregateTarget", t_libs, "GameLibs",
        "{isa = PBXAggregateTarget; buildConfigurationList = %s; buildPhases = %s; dependencies = (); name = GameLibs; productName = GameLibs; }" % (cl_libs, qlist([script], 3)))
    proxy, dep = uid("proxy"), uid("dep")
    add("PBXContainerItemProxy", proxy, "PBXContainerItemProxy", "{isa = PBXContainerItemProxy; containerPortal = %s; proxyType = 1; remoteGlobalIDString = %s; remoteInfo = GameLibs; }" % (proj, t_libs))
    add("PBXTargetDependency", dep, "PBXTargetDependency", "{isa = PBXTargetDependency; target = %s; targetProxy = %s; }" % (t_libs, proxy))
    sources_phase, frameworks_phase = uid("phase:sources"), uid("phase:frameworks")
    add("PBXSourcesBuildPhase", sources_phase, "Sources", "{isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = %s; runOnlyForDeploymentPostprocessing = 0; }" % qlist(build_ids, 3))
    add("PBXFrameworksBuildPhase", frameworks_phase, "Frameworks", "{isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0; }")
    add("PBXNativeTarget", t_app, "Pentamoor",
        "{isa = PBXNativeTarget; buildConfigurationList = %s; buildPhases = %s; buildRules = (); dependencies = %s; name = Pentamoor; productName = Pentamoor; productReference = %s; "
        "productType = \"com.apple.product-type.application\"; }" % (cl_app, qlist([sources_phase, frameworks_phase], 3), qlist([dep], 3), product_ref))
    attrs = "{LastUpgradeCheck = 2600; TargetAttributes = {%s = {CreatedOnToolsVersion = 26.0; }; %s = {CreatedOnToolsVersion = 26.0; %s}; }; }" % (
        t_libs, t_app, ('DevelopmentTeam = %s; ' % q(team)) if team else "")
    add("PBXProject", proj, "Project object",
        "{isa = PBXProject; attributes = %s; buildConfigurationList = %s; compatibilityVersion = \"Xcode 14.0\"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en, Base, ); "
        "mainGroup = %s; productRefGroup = %s; projectDirPath = \"\"; projectRoot = \"\"; targets = %s; }" % (attrs, cl_proj, g_main, g_prod, qlist([t_app, t_libs], 3)))

    # build settings
    defs = ["LIFT_BACKEND_FLAT4G=1", "LIFT_PREEMPT=1", "PORT_IOS=1", "PORT_STATIC_MODULES=1"] + ["PORT_STATIC_%s=1" % p.upper() for p in PROGRAMS]
    ldflags = ["$(inherited)"] + ["$(IOS_ROOT)/dist/ios/$(IOS_PLAT)/game_%s.o" % p for p in PROGRAMS] + ["$(IOS_ROOT)/dist/work-ios/sdl-build/$(IOS_PLAT)/Release-$(PLATFORM_NAME)/libSDL2.a"]
    for f in FRAMEWORKS:
        ldflags += ["-framework", f]
    ldflags += ["-liconv"]
    common = {
        "ARCHS": "arm64", "ONLY_ACTIVE_ARCH": "NO", "SDKROOT": "iphoneos", "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator", "IPHONEOS_DEPLOYMENT_TARGET": MIN_IOS,
        "TARGETED_DEVICE_FAMILY": "2", "CLANG_ENABLE_OBJC_ARC": "YES", "GCC_C_LANGUAGE_STANDARD": "gnu99", "ENABLE_USER_SCRIPT_SANDBOXING": "NO",
        "IOS_ROOT": ROOT, "ALWAYS_SEARCH_USER_PATHS": "NO", "COPY_PHASE_STRIP": "NO", "STRIP_INSTALLED_PRODUCT": "NO",
    }

    def cfg(name, settings, raw=None):
        body = "{\n\t\t\tisa = XCBuildConfiguration;\n\t\t\tbuildSettings = {\n"
        for k in sorted(settings):
            v = settings[k]
            body += "\t\t\t\t%s = %s;\n" % (q(k), qlist(v, 4) if isinstance(v, list) else q(v))
        body += "\t\t\t};\n\t\t\tname = %s;\n\t\t}" % name
        return body

    def cfglist(oid, comment, ids):
        add("XCConfigurationList", oid, comment, "{\n\t\t\tisa = XCConfigurationList;\n\t\t\tbuildConfigurations = %s;\n\t\t\tdefaultConfigurationIsVisible = 0;\n\t\t\tdefaultConfigurationName = Release;\n\t\t}" % qlist(ids, 3))

    proj_ids, libs_ids, app_ids = [], [], []
    for name, opt, dbg in (("Debug", "0", "dwarf"), ("Release", "2", "dwarf-with-dsym")):
        s = dict(common)
        s.update({"GCC_OPTIMIZATION_LEVEL": opt, "DEBUG_INFORMATION_FORMAT": dbg, "GCC_WARN_INHIBIT_ALL_WARNINGS": "NO"})
        pid = uid("cfg:proj:" + name)
        add("XCBuildConfiguration", pid, name, cfg(name, s))
        proj_ids.append(pid)
        lid = uid("cfg:libs:" + name)
        add("XCBuildConfiguration", lid, name, cfg(name, {"PRODUCT_NAME": "$(TARGET_NAME)"}))
        libs_ids.append(lid)
        a = {
            "PRODUCT_NAME": "Pentamoor", "PRODUCT_BUNDLE_IDENTIFIER": bundle_id, "MARKETING_VERSION": "0.0.1", "CURRENT_PROJECT_VERSION": "1",
            "INFOPLIST_FILE": plist_path, "GENERATE_INFOPLIST_FILE": "NO", "CODE_SIGN_STYLE": "Automatic", "DEVELOPMENT_TEAM": team or "",
            "GCC_PREPROCESSOR_DEFINITIONS": ["$(inherited)"] + defs,
            "HEADER_SEARCH_PATHS": ["$(IOS_ROOT)/src/native", "$(IOS_ROOT)/dist/work-ios/sdl-src/include"],
            "USER_HEADER_SEARCH_PATHS": ["$(IOS_ROOT)/src/port"],
            "OTHER_CFLAGS": ["-Wno-unused-parameter", "-Wno-deprecated-declarations"],
            "OTHER_LDFLAGS": ldflags,
            "IOS_PLAT[sdk=iphoneos*]": "device", "IOS_PLAT[sdk=iphonesimulator*]": "simulator",
            "OTHER_LDFLAGS[sdk=iphoneos*]": ["$(inherited)", "-Wl,-platform_version,ios,%s,%s" % (MIN_IOS, LINK_SDK)],
            "OTHER_LDFLAGS[sdk=iphonesimulator*]": ["$(inherited)", "-Wl,-platform_version,ios-simulator,%s,%s" % (MIN_IOS, LINK_SDK)],
            "ASSETCATALOG_COMPILER_APPICON_NAME": "",
        }
        if entitlements:
            a["CODE_SIGN_ENTITLEMENTS"] = ent_path
        aid = uid("cfg:app:" + name)
        add("XCBuildConfiguration", aid, name, cfg(name, a))
        app_ids.append(aid)
    cfglist(cl_proj, 'Build configuration list for PBXProject "Pentamoor"', proj_ids)
    cfglist(cl_libs, 'Build configuration list for PBXAggregateTarget "GameLibs"', libs_ids)
    cfglist(cl_app, 'Build configuration list for PBXNativeTarget "Pentamoor"', app_ids)

    text = "// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {\n\t};\n\tobjectVersion = 56;\n\tobjects = {\n"
    for kind in sorted(sections):
        if not sections[kind]:
            continue
        text += "\n/* Begin %s section */\n" % kind + "".join(sorted(sections[kind])) + "/* End %s section */\n" % kind
    text += "\t};\n\trootObject = %s /* Project object */;\n}\n" % proj

    proj_dir = os.path.join(out_dir, "Pentamoor.xcodeproj")
    os.makedirs(os.path.join(proj_dir, "xcshareddata", "xcschemes"), exist_ok=True)
    with open(os.path.join(proj_dir, "project.pbxproj"), "w") as f:
        f.write(text)
    ref = ('<BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "%s" BuildableName = "Pentamoor.app" BlueprintName = "Pentamoor" ReferencedContainer = "container:Pentamoor.xcodeproj"></BuildableReference>' % t_app)
    scheme = ('<?xml version="1.0" encoding="UTF-8"?>\n<Scheme LastUpgradeVersion = "2600" version = "1.7">\n   <BuildAction parallelizeBuildables = "YES" buildImplicitDependencies = "YES">\n'
              '      <BuildActionEntries>\n         <BuildActionEntry buildForTesting = "YES" buildForRunning = "YES" buildForProfiling = "YES" buildForArchiving = "YES" buildForAnalyzing = "YES">\n'
              '            %s\n         </BuildActionEntry>\n      </BuildActionEntries>\n   </BuildAction>\n'
              '   <TestAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv = "YES"></TestAction>\n'
              '   <LaunchAction buildConfiguration = "Release" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle = "0" useCustomWorkingDirectory = "NO" ignoresPersistentStateOnLaunch = "NO" debugDocumentVersioning = "YES" debugServiceExtension = "internal" allowLocationSimulation = "YES">\n'
              '      <BuildableProductRunnable runnableDebuggingMode = "0">\n         %s\n      </BuildableProductRunnable>\n   </LaunchAction>\n'
              '   <ProfileAction buildConfiguration = "Release" shouldUseLaunchSchemeArgsEnv = "YES" savedToolIdentifier = "" useCustomWorkingDirectory = "NO" debugDocumentVersioning = "YES"></ProfileAction>\n'
              '   <AnalyzeAction buildConfiguration = "Debug"></AnalyzeAction>\n   <ArchiveAction buildConfiguration = "Release" revealArchiveInOrganizer = "YES"></ArchiveAction>\n</Scheme>\n') % (ref, ref)
    with open(os.path.join(proj_dir, "xcshareddata", "xcschemes", "Pentamoor.xcscheme"), "w") as f:
        f.write(scheme)
    return proj_dir


def default_bundle_id():
    login = re.sub(r"[^a-z0-9]+", "-", os.environ.get("USER", "user").lower()).strip("-") or "user"
    return "org.pentamoor.app." + login


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--team", default="", help="your Apple developer team id (10 characters); or choose it in Xcode, Signing & Capabilities")
    ap.add_argument("--bundle-id", default=default_bundle_id(), help="default: %(default)s (a device needs one that is yours: the same id as any other app of your team is refused)")
    ap.add_argument("--entitlements", action="store_true", help="sign with tools/ios/Pentamoor.entitlements (extended virtual addressing, increased memory limit)")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "ios", "xcode"), help="where the project goes (default dist/ios/xcode, git-ignored)")
    a = ap.parse_args(argv)
    if a.team and not re.fullmatch(r"[A-Z0-9]{10}", a.team):
        raise SystemExit("gen_xcodeproj: --team is the 10-character team id (Xcode > Settings > Accounts, or developer.apple.com > Membership), not a name")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", a.bundle_id):
        raise SystemExit("gen_xcodeproj: a bundle id has only letters, digits, dots and hyphens")
    p = build(a.team, a.bundle_id, a.entitlements, os.path.abspath(a.out))
    print("wrote", p)
    print("next: tools/ios/build_ios.sh device libs   (optional: the project's first build step does it)\n      open %s   and choose your team in Signing & Capabilities" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
