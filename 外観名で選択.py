import adsk.core
import adsk.fusion
import traceback
import os

# ---- 定数 ----
CMD_ID = 'SelectByAppearanceCmd_v2'
CMD_ID_OLD = 'SelectByAppearanceCmd'
CMD_NAME = '外観名で選択'
CMD_DESC = '使用中の外観をチェックボックスで選択し、該当フェースを選択状態にします。'
PANEL_ID = 'SolidModifyPanel'          # ソリッドタブ > 修正パネル
RESOURCES_DIR = os.path.join(os.path.dirname(__file__), 'resources', 'Command2')

# グローバルリスト（イベントハンドラを GC から守るため）
_handlers = []
_is_executed = False


# ---- ユーティリティ ----
def get_all_bodies(root_comp):
    """
    ルートコンポーネント内の全ボディ（プロキシ含む）を取得。
    """
    bodies = list(root_comp.bRepBodies)
    for occ in root_comp.allOccurrences:
        if occ.bRepBodies:
            bodies.extend(list(occ.bRepBodies))
    return bodies


def get_inherited_appearance_name(body):
    """
    ボディが親（コンポーネントやアセンブリのオカレンス）から
    継承している外観の名前を取得する
    """
    if body.appearance:
        return body.appearance.name
        
    if hasattr(body, 'assemblyContext') and body.assemblyContext:
        occ = body.assemblyContext
        while occ:
            if occ.appearance:
                return occ.appearance.name
            occ = occ.parentOccurrence
        comp = body.assemblyContext.component
        if comp and comp.appearance:
            return comp.appearance.name
    else:
        if body.parentComponent and body.parentComponent.appearance:
            return body.parentComponent.appearance.name
            
    return None


def collect_appearances(design):
    """
    デザイン内の全フェースを走査し、
    コンポーネントからの継承も含めて実際に適用されている外観名の一覧を返す。
    """
    names = set()
    root = design.rootComponent
    for body in get_all_bodies(root):
        inherited_app = get_inherited_appearance_name(body)
        for face in body.faces:
            if face.appearance:
                names.add(face.appearance.name)
            elif inherited_app:
                names.add(inherited_app)
    return sorted(names)


# ---- イベントハンドラ ----
class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            global _is_executed
            _is_executed = False

            cmd = args.command
            inputs = cmd.commandInputs

            app = adsk.core.Application.get()
            design = adsk.fusion.Design.cast(app.activeProduct)

            if not design:
                app.userInterface.messageBox('アクティブなデザインが見つかりません。')
                return

            appearance_names = collect_appearances(design)

            if not appearance_names:
                app.userInterface.messageBox(
                    '使用中の外観が見つかりませんでした。\n'
                    'コンポーネント、ボディ、またはフェースに外観が設定されているか確認してください。'
                )
                return

            for i, name in enumerate(appearance_names):
                inputs.addBoolValueInput(f'app_cb_{i}', name, True, '', False)

            on_execute = CommandExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)

            on_input_changed = CommandInputChangedHandler()
            cmd.inputChanged.add(on_input_changed)
            _handlers.append(on_input_changed)

            on_destroy = CommandDestroyHandler()
            cmd.destroy.add(on_destroy)
            _handlers.append(on_destroy)

        except:
            app = adsk.core.Application.get()
            if app and app.userInterface:
                app.userInterface.messageBox(
                    'CommandCreated エラー:\n{}'.format(traceback.format_exc())
                )


class CommandInputChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            app = adsk.core.Application.get()
            ui = app.userInterface
            design = adsk.fusion.Design.cast(app.activeProduct)
            inputs = args.inputs

            selected_names = set()
            for i in range(inputs.count):
                inp = inputs.item(i)
                if inp.id.startswith('app_cb_') and getattr(inp, 'value', False):
                    selected_names.add(inp.name)

            ui.activeSelections.clear()
            if not selected_names:
                return

            for body in get_all_bodies(design.rootComponent):
                inherited_app = get_inherited_appearance_name(body)
                for face in body.faces:
                    face_app_name = face.appearance.name if face.appearance else inherited_app
                    if face_app_name in selected_names:
                        ui.activeSelections.add(face)
        except:
            pass


class CommandDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            global _is_executed
            if not _is_executed:
                app = adsk.core.Application.get()
                app.userInterface.activeSelections.clear()
        except:
            pass


class CommandExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        global _is_executed
        _is_executed = True
        ui = None
        try:
            app = adsk.core.Application.get()
            ui = app.userInterface
            design = adsk.fusion.Design.cast(app.activeProduct)
            inputs = args.command.commandInputs

            selected_names = set()
            for i in range(inputs.count):
                inp = inputs.item(i)
                if inp.id.startswith('app_cb_') and getattr(inp, 'value', False):
                    selected_names.add(inp.name)

            if not selected_names:
                ui.messageBox('外観が1つも選択されていません。')
                return

            matched_faces = []
            for body in get_all_bodies(design.rootComponent):
                inherited_app = get_inherited_appearance_name(body)
                for face in body.faces:
                    face_app_name = face.appearance.name if face.appearance else inherited_app
                    if face_app_name in selected_names:
                        matched_faces.append(face)

            if not matched_faces:
                names_str = '、'.join(sorted(selected_names))
                ui.messageBox(f'外観「{names_str}」が設定されたフェースは見つかりませんでした。')
                return

            selections = ui.activeSelections
            selections.clear()
            for face in matched_faces:
                selections.add(face)

        except:
            if ui:
                ui.messageBox('CommandExecute エラー:\n{}'.format(traceback.format_exc()))


# ---- アドイン エントリポイント ----
def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        cmd_defs = ui.commandDefinitions
        
        old_cmd_def = cmd_defs.itemById(CMD_ID_OLD)
        if old_cmd_def:
            old_cmd_def.deleteMe()

        cmd_def = cmd_defs.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()

        cmd_def = cmd_defs.addButtonDefinition(
            CMD_ID,
            CMD_NAME,
            CMD_DESC,
            RESOURCES_DIR
        )

        on_created = CommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        solid_ws = ui.workspaces.itemById('FusionSolidEnvironment')
        if solid_ws:
            modify_panel = solid_ws.toolbarPanels.itemById(PANEL_ID)
            if modify_panel:
                old_ctrl = modify_panel.controls.itemById(CMD_ID_OLD)
                if old_ctrl:
                    old_ctrl.deleteMe()
                ctrl = modify_panel.controls.itemById(CMD_ID)
                if ctrl:
                    ctrl.deleteMe()
                modify_panel.controls.addCommand(cmd_def)

        adsk.autoTerminate(False)

    except:
        if ui:
            ui.messageBox('起動エラー:\n{}'.format(traceback.format_exc()))


def stop(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        solid_ws = ui.workspaces.itemById('FusionSolidEnvironment')
        if solid_ws:
            modify_panel = solid_ws.toolbarPanels.itemById(PANEL_ID)
            if modify_panel:
                old_ctrl = modify_panel.controls.itemById(CMD_ID_OLD)
                if old_ctrl:
                    old_ctrl.deleteMe()
                ctrl = modify_panel.controls.itemById(CMD_ID)
                if ctrl:
                    ctrl.deleteMe()

        old_cmd_def = ui.commandDefinitions.itemById(CMD_ID_OLD)
        if old_cmd_def:
            old_cmd_def.deleteMe()
            
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()

        _handlers.clear()

    except:
        if ui:
            ui.messageBox('停止エラー:\n{}'.format(traceback.format_exc()))
