(* SyringeTwin - OpenPLC connection test (PLC_SPEC.md section 7).
   Upload in OpenPLC Runtime: Programs > Upload Program > Compile > Start PLC.
   Pass: %MW0 = 41 -> %QW0 = 42; %MW1 = 1 -> %QX0.0 = TRUE; %QW1 rises ~50/s. *)

PROGRAM spike
  VAR
    in_value AT %MW0 : INT;
    in_flag AT %MW1 : INT;
    out_value AT %QW0 : INT;
    scan_count AT %QW1 : INT;
    out_flag AT %QX0.0 : BOOL;
  END_VAR

  out_value := in_value + 1;
  out_flag := in_flag <> 0;
  IF scan_count >= 30000 THEN
    scan_count := 0;
  ELSE
    scan_count := scan_count + 1;
  END_IF;
END_PROGRAM


CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK task0(INTERVAL := T#20ms,PRIORITY := 0);
    PROGRAM instance0 WITH task0 : spike;
  END_RESOURCE
END_CONFIGURATION
