from tinygrad.lazy import LazyBuffer
from tinygrad.codegen.cstyle import render_cl
from tinygrad.helpers import dtypes, DType
from tinygrad.codegen.linearizer import LocalBuffer
from tinygrad.codegen.cstyle import CStyleLanguage
from typing import List, Union
from tinygrad.runtime.lib import RawConst
from tinygrad.ops import UnaryOps, BinaryOps, FusedOps
import math
from typing import Tuple

type_map = {dtypes.float: "f32", dtypes.half: "f16", dtypes.int32: "i32", dtypes.uint32: "u32", dtypes.bool: "bool"} 
class WGSLLanguage(CStyleLanguage):
  gid = [f"i32(gindex.{'xyz'[x]})" for x in range(3)]
  lid = [f"i32(lindex.{'xyz'[x]})" for x in range(3)]
  size_prefix = "let"
  barrier="workgroupBarrier();"
  generic_var_prefix = "var "
  external_local_bufs = True
  code_for_op = {
    UnaryOps.EXP2: lambda x: f"exp2({x})", UnaryOps.LOG2: lambda x: f"log2({x})", UnaryOps.SIN: lambda x: f"sin({x})", UnaryOps.SQRT: lambda x: f"sqrt({x})",
    BinaryOps.ADD: lambda x,y: f"({x}+{y})", BinaryOps.SUB: lambda x,y: f"({x}-{y})", BinaryOps.MUL: lambda x,y: f"({x}*{y})", BinaryOps.DIV: lambda x,y: f"({x}/{y})",
    BinaryOps.MAX: lambda x,y: f"max({x},{y})", BinaryOps.CMPEQ: lambda x,y: f"f32({x}=={y})",
    FusedOps.MULACC: lambda x,y,z: f"fma({x},{y},{z})",
  }

  def render_local(self, name: str, size: int):
    return f"var<workgroup> {name}: array<f32,{size}>;"
  
  def render_const(self, x:Union[float,int], var_dtype) -> str:
    if math.isinf(x): val = ("-" if x < 0 else "") + "0x1.fffffep+127f"
    else: val = f"{x}" + ("" if dtypes.is_int(var_dtype) else "f")
    return self.render_cast([val]*var_dtype.sz, var_dtype) if var_dtype.sz > 1 else val
  
  def render_kernel(self, kernel:List[str], bufs:List[Union[LocalBuffer,LazyBuffer]], bufnames:List[str], global_size:List[int], local_size:List[int], prekernel:List[str]) -> Tuple[str, List[int], List[int]]:
    local_size = local_size[::-1] if len(local_size) else [1]
    bind_it = iter(range(len(bufs)))
    prg = "\n".join(prekernel+[f"@group(0) @binding({next(bind_it)}) var<storage,read_write> data{i}: array<{type_map[x.dtype]}>;" for i,x in enumerate(bufs) if not isinstance(x, LocalBuffer) and not isinstance(x.realized, RawConst)])
    prg += f"\n@compute @workgroup_size({','.join([str(x) for x in local_size])}) fn KERNEL_NAME_PLACEHOLDER(@builtin(workgroup_id) gindex: vec3<u32>, @builtin(local_invocation_id) lindex: vec3<u32>) {{\n" + "\n".join(kernel) + "\n}"
    return prg, global_size[::-1] if len(global_size) else [1], local_size
  
  def render_for(self, expr:str, _min:int, _max:int) -> str:
    return f"for(var {expr} = {_min}; {expr} <= {_max}; {expr}++) {{"
  
  def render_conditional(self, cond:str, x:str, y:str) -> str:
    return f"select(f32({y}), {x}, bool({cond}))"
  
  def render_load(self, output_dtype, buf_name, buf_dtype, idx, local=False) -> str:
    return f"f32({super().render_load(output_dtype, buf_name, buf_dtype, idx, local)})"
  
  def render_store(self, buf_name:str, buf_dtype:DType, var_name:str, var_dtype:DType, idx, local=False) -> str:
    if buf_dtype != var_dtype:
      var_name = f"{type_map[buf_dtype]}({var_name})"
    return f"{buf_name}[{idx.render(render_cl)}] = {var_name};"