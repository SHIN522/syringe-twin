(* SyringeTwin cell supervisor - OpenPLC Runtime program.
   Behaviour: docs/plc/PLC_SPEC.md. Addresses: docs/plc/tag_dictionary.csv.
   Rung IDs (P1-R1 ...) match the specification and twin/plc_bridge.py.
   Upload: Programs > Upload Program > Compile > Start PLC (Modbus server on). *)

PROGRAM syringetwin
  VAR
    (* ---- twin -> PLC (%MW = Modbus holding registers 1024+) ---- *)
    CMD_START AT %MW0 : INT;
    CMD_STOP AT %MW1 : INT;
    CMD_RESET AT %MW2 : INT;
    I_ESTOP_OK AT %MW3 : INT;
    I_S2_TOOL_OK AT %MW4 : INT;
    AI_S2_FORCE AT %MW5 : INT;
    S2_PRESS_SEQ AT %MW6 : INT;
    GOOD_SEQ AT %MW7 : INT;
    REJECT_SEQ AT %MW8 : INT;
    HEARTBEAT AT %MW9 : INT;
    TWIN_WARN AT %MW10 : INT;
    ANY_BLOCKED AT %MW11 : INT;
    S2_DONE AT %MW12 : INT;
    B3_ROOM AT %MW13 : INT;
    IN_SEQ AT %MW14 : INT;
    CMD_INJECT_F201 AT %MW15 : INT;

    (* ---- PLC -> twin: coils ---- *)
    M_SYS_RUN AT %QX0.0 : BOOL;
    Q_LAMP_GREEN AT %QX0.1 : BOOL;
    Q_LAMP_AMBER AT %QX0.2 : BOOL;
    Q_LAMP_RED AT %QX0.3 : BOOL;
    Q_HORN AT %QX0.4 : BOOL;
    F201 AT %QX0.5 : BOOL;
    F001 AT %QX0.6 : BOOL;
    F002 AT %QX0.7 : BOOL;
    M_ANY_FAULT AT %QX1.0 : BOOL;
    F201_INJECTED AT %QX1.1 : BOOL;
    S2_RELEASE_PERMIT AT %QX1.2 : BOOL;
    M_S2_REPAIRED AT %QX1.3 : BOOL;

    (* ---- PLC -> twin: holding registers %QW ---- *)
    S2_VERDICT_SEQ AT %QW0 : INT;
    PLC_HEARTBEAT AT %QW1 : INT;
    C_IN_CV AT %QW2 : INT;
    C_GOOD_CV AT %QW3 : INT;
    C_REJECT_CV AT %QW4 : INT;
    BOX_FILL AT %QW5 : INT;
    BOXES_TOTAL AT %QW6 : INT;
  END_VAR

  (* ---- internal (matiec needs these in their own VAR block) ---- *)
  VAR
    START_B : BOOL;  STOP_B : BOOL;  RESET_B : BOOL;
    ESTOP_OK : BOOL; TOOL_OK : BOOL;
    START_RE : BOOL; RESET_RE : BOOL; INJECT_RE : BOOL; TOOL_OK_RE : BOOL;
    NEW_PRESS : BOOL; NEW_GOOD : BOOL; NEW_REJECT : BOOL; NEW_IN : BOOL; HB_CHANGED : BOOL;
    LAST_PRESS_SEQ : INT; LAST_GOOD_SEQ : INT; LAST_REJECT_SEQ : INT; LAST_IN_SEQ : INT; LAST_HB : INT;
    LINK_SEEN : BOOL;
    BLINK : BOOL;
    TRIP_SP : INT := 1600;   (* 160.0 N, brief section 4 *)
    TRIG_START : R_TRIG; TRIG_RESET : R_TRIG; TRIG_INJ : R_TRIG; TRIG_TOOL : R_TRIG;
    BLINK_T1 : TON; BLINK_T2 : TON;
    T_WD : TON;
    C_IN : CTU; C_GOOD : CTU; C_REJECT : CTU; C_BOX : CTU;
  END_VAR

  (* ================= IO_MAP ================= *)
  START_B := CMD_START <> 0;
  STOP_B := CMD_STOP <> 0;
  RESET_B := CMD_RESET <> 0;
  ESTOP_OK := I_ESTOP_OK <> 0;
  TOOL_OK := I_S2_TOOL_OK <> 0;
  TRIG_START(CLK := START_B);  START_RE := TRIG_START.Q;
  TRIG_RESET(CLK := RESET_B);  RESET_RE := TRIG_RESET.Q;
  TRIG_INJ(CLK := CMD_INJECT_F201 <> 0);  INJECT_RE := TRIG_INJ.Q;
  TRIG_TOOL(CLK := TOOL_OK);   TOOL_OK_RE := TRIG_TOOL.Q;

  NEW_PRESS := S2_PRESS_SEQ <> LAST_PRESS_SEQ;
  NEW_GOOD := GOOD_SEQ <> LAST_GOOD_SEQ;        LAST_GOOD_SEQ := GOOD_SEQ;
  NEW_REJECT := REJECT_SEQ <> LAST_REJECT_SEQ;  LAST_REJECT_SEQ := REJECT_SEQ;
  NEW_IN := IN_SEQ <> LAST_IN_SEQ;              LAST_IN_SEQ := IN_SEQ;
  HB_CHANGED := HEARTBEAT <> LAST_HB;           LAST_HB := HEARTBEAT;
  IF HB_CHANGED THEN LINK_SEEN := TRUE; END_IF;
  IF PLC_HEARTBEAT >= 30000 THEN PLC_HEARTBEAT := 0; ELSE PLC_HEARTBEAT := PLC_HEARTBEAT + 1; END_IF;

  (* ================= P5 - S2 force and F201 ================= *)
  (* P5-R1 overload on a new press sample *)
  IF NEW_PRESS AND (AI_S2_FORCE > TRIP_SP) THEN
    F201 := TRUE;
    M_S2_REPAIRED := FALSE;
  END_IF;
  (* P5-R2 injected overload (operator test) *)
  IF INJECT_RE THEN
    F201 := TRUE;
    F201_INJECTED := TRUE;
    M_S2_REPAIRED := FALSE;
  END_IF;
  (* P5-R3 verdict echo = INSERT permissive for this sample *)
  IF NEW_PRESS THEN
    S2_VERDICT_SEQ := S2_PRESS_SEQ;
    LAST_PRESS_SEQ := S2_PRESS_SEQ;
  END_IF;

  (* ================= P8 - alarms and recovery ================= *)
  (* P8-R1 repair acknowledged *)
  IF F201 AND TOOL_OK_RE THEN M_S2_REPAIRED := TRUE; END_IF;
  (* P8-R2 F201 reset needs a completed repair *)
  IF RESET_RE AND F201 AND M_S2_REPAIRED AND TOOL_OK THEN
    F201 := FALSE;
    M_S2_REPAIRED := FALSE;
    F201_INJECTED := FALSE;
  END_IF;
  (* P8-R3 link watchdog: twin heartbeat unchanged for 1 s (armed after the first heartbeat) *)
  T_WD(IN := LINK_SEEN AND NOT HB_CHANGED, PT := T#1s);
  IF T_WD.Q THEN F002 := TRUE; END_IF;
  (* P8-R4 F002 reset only with a live link *)
  IF RESET_RE AND NOT T_WD.Q THEN F002 := FALSE; END_IF;

  (* ================= P1 - master control ================= *)
  (* P1-R2 E-stop latch *)
  IF NOT ESTOP_OK THEN F001 := TRUE; END_IF;
  IF RESET_RE AND ESTOP_OK THEN F001 := FALSE; END_IF;
  (* P8-R5 summary *)
  M_ANY_FAULT := F001 OR F201 OR F002;
  (* P1-R1 run seal-in: only F001/F002 stop the line (D1) *)
  M_SYS_RUN := (START_RE OR M_SYS_RUN) AND NOT STOP_B AND NOT F001 AND NOT F002;
  (* P1-R3 blink 0.5 s / 0.5 s *)
  BLINK_T1(IN := NOT BLINK_T2.Q, PT := T#500ms);
  BLINK_T2(IN := BLINK_T1.Q, PT := T#500ms);
  BLINK := BLINK_T1.Q;
  (* P1-R4 .. R6 tower light: red > amber > green *)
  Q_LAMP_RED := M_ANY_FAULT AND BLINK;
  Q_HORN := M_ANY_FAULT;
  Q_LAMP_AMBER := NOT M_ANY_FAULT AND ((TWIN_WARN <> 0) OR (ANY_BLOCKED <> 0));
  Q_LAMP_GREEN := M_SYS_RUN AND NOT M_ANY_FAULT AND NOT Q_LAMP_AMBER;

  (* ================= P9 - counters ================= *)
  C_IN(CU := NEW_IN, R := FALSE, PV := 32000);
  C_GOOD(CU := NEW_GOOD, R := FALSE, PV := 32000);
  C_REJECT(CU := NEW_REJECT, R := FALSE, PV := 32000);
  C_BOX(CU := NEW_GOOD, R := FALSE, PV := 10);
  IF C_BOX.Q THEN
    BOXES_TOTAL := BOXES_TOTAL + 1;
    C_BOX(CU := FALSE, R := TRUE, PV := 10);
    C_BOX(CU := FALSE, R := FALSE, PV := 10);
  END_IF;
  C_IN_CV := C_IN.CV;
  C_GOOD_CV := C_GOOD.CV;
  C_REJECT_CV := C_REJECT.CV;
  BOX_FILL := C_BOX.CV;

  (* ================= P2 - S2 release permit (SHOULD) ================= *)
  S2_RELEASE_PERMIT := (S2_DONE <> 0) AND (B3_ROOM <> 0) AND M_SYS_RUN AND NOT F201;
END_PROGRAM


CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#20ms,PRIORITY := 0);
    PROGRAM instance0 WITH task0 : syringetwin;
  END_RESOURCE
END_CONFIGURATION
