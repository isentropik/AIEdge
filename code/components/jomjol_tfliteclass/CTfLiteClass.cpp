#include "CTfLiteClass.h"
#include "PolarDecoder.h"
#include <cstring>
#include <cstdint>
#include "mbedtls/sha256.h"
#include "ClassLogFile.h"
#include "Helper.h"
#include "psram.h"
#include "esp_log.h"
#include "../../include/defines.h"

#include <sys/stat.h>

// #define DEBUG_DETAIL_ON


static const char *TAG = "TFLITE";


bool CTfLiteClass::MakeStaticResolver()
{
  if (resolverAttempted) return resolverReady;
  resolverAttempted = true;
  resolverReady = true;
  resolverReady &= resolver.AddFullyConnected() == kTfLiteOk;
  resolverReady &= resolver.AddReshape() == kTfLiteOk;
  resolverReady &= resolver.AddSoftmax() == kTfLiteOk;
  resolverReady &= resolver.AddConv2D() == kTfLiteOk;
  resolverReady &= resolver.AddMaxPool2D() == kTfLiteOk;
  resolverReady &= resolver.AddQuantize() == kTfLiteOk;
  resolverReady &= resolver.AddMul() == kTfLiteOk;
  resolverReady &= resolver.AddAdd() == kTfLiteOk;
  resolverReady &= resolver.AddLeakyRelu() == kTfLiteOk;
  resolverReady &= resolver.AddDequantize() == kTfLiteOk;
  return resolverReady;
}

void CTfLiteClass::ResetInterpreter()
{
  // Destroy the interpreter while its model bytes are still intact. Keep the
  // shared allocation owned by this object until destruction, not each reload.
  delete interpreter;
  interpreter = nullptr;
  input = nullptr;
  output = nullptr;
}



float CTfLiteClass::GetOutputValue(int nr)
{
    TfLiteTensor* output2 = this->interpreter->output(0);

    int numeroutput = output2->dims->data[1];
    if ((nr+1) > numeroutput)
      return -1000;

    return output2->data.f[nr];
}


int CTfLiteClass::GetClassFromImageBasis(CImageBasis *rs)
{
    if (!LoadInputImageBasis(rs))
      return -1000;

    Invoke();

    return GetOutClassification();
}


int CTfLiteClass::GetOutClassification(int _von, int _bis)
{
  TfLiteTensor* output2 = interpreter->output(0);

  float zw_max;
  float zw;
  int zw_class;

  if (output2 == NULL)
    return -1;

  int numeroutput = output2->dims->data[1];
  //ESP_LOGD(TAG, "number output neurons: %d", numeroutput);

  if (_bis == -1)
    _bis = numeroutput -1;

  if (_von == -1)
    _von = 0;

  if (_bis >= numeroutput)
  {
    ESP_LOGD(TAG, "NUMBER OF OUTPUT NEURONS does not match required classification!");
    return -1;
  }

  zw_max = output2->data.f[_von];
  zw_class = _von;
  for (int i = _von + 1; i <= _bis; ++i)
  {
    zw = output2->data.f[i];
    if (zw > zw_max)
    {
        zw_max = zw;
        zw_class = i;
    }
  }
  return (zw_class - _von);
}


void CTfLiteClass::GetInputDimension(bool silent = false)
{
  TfLiteTensor* input2 = this->interpreter->input(0);

  int numdim = input2->dims->size;
  if (!silent)  ESP_LOGD(TAG, "NumDimension: %d", numdim);

  int sizeofdim;
  for (int j = 0; j < numdim; ++j)
  {
    sizeofdim = input2->dims->data[j];
    if (!silent) ESP_LOGD(TAG, "SizeOfDimension %d: %d", j, sizeofdim);
    if (j == 1) im_height = sizeofdim;
    if (j == 2) im_width = sizeofdim;
    if (j == 3) im_channel = sizeofdim;
  }
}


int CTfLiteClass::ReadInputDimenstion(int _dim)
{
  if (_dim == 0)
    return im_width;
  if (_dim == 1)
    return im_height;
  if (_dim == 2)
    return im_channel;

  return -1;
}


int CTfLiteClass::GetAnzOutPut(bool silent)
{
  TfLiteTensor* output2 = this->interpreter->output(0);

  int numdim = output2->dims->size;
  if (!silent) ESP_LOGD(TAG, "NumDimension: %d", numdim);

  int sizeofdim;
  for (int j = 0; j < numdim; ++j)
  {
    sizeofdim = output2->dims->data[j];
    if (!silent) ESP_LOGD(TAG, "SizeOfDimension %d: %d", j, sizeofdim);
  }


  float fo;

  // Process the inference results.
  int numeroutput = output2->dims->data[1];
  for (int i = 0; i < numeroutput; ++i)
  {
   fo = output2->data.f[i];
    if (!silent) ESP_LOGD(TAG, "Result %d: %f", i, fo);
  }
  return numeroutput;
}


void CTfLiteClass::Invoke()
{
    if (interpreter != nullptr)
      interpreter->Invoke();
}

bool CTfLiteClass::HasPolarTensorContract()
{
    if (!interpreter) return false;
    TfLiteTensor* in = interpreter->input(0);
    TfLiteTensor* out = interpreter->output(0);
    if (!in || !out || !in->dims || !out->dims ||
        in->type != kTfLiteInt8 || out->type != kTfLiteInt8 ||
        in->dims->size != 3 || out->dims->size != 2 ||
        in->dims->data[0] != 1 || in->dims->data[1] != 384 || in->dims->data[2] != 40 ||
        out->dims->data[0] != 1 || out->dims->data[1] != 360 ||
        in->bytes != 384 * 40 || out->bytes != 360 ||
        !in->data.int8 || !out->data.int8) return false;
    // Reject incompatible models rather than silently decoding another quantization.
    if (!std::isfinite(in->params.scale) || !std::isfinite(out->params.scale) ||
        std::fabs(in->params.scale - 0.006855103187263012f) > 1e-9f ||
        in->params.zero_point != -53 ||
        out->params.scale != 0.00390625f || out->params.zero_point != -128) return false;
    return true;
}

bool CTfLiteClass::InvokePolar(const int8_t* features, size_t count)
{
    if (!features || count != 384 * 40 || !HasPolarTensorContract()) return false;
    TfLiteTensor* in = interpreter->input(0);
    std::memcpy(in->data.int8, features, count);
    return interpreter->Invoke() == kTfLiteOk;
}

bool CTfLiteClass::InferPolar(const int8_t* features, size_t count, bool ccw, float& result)
{
    if (!InvokePolar(features,count)) return false;
    return polar::decode(interpreter->output(0)->data.int8, 360, ccw, result);
}

bool CTfLiteClass::InferPolarScores(const int8_t* features,size_t count,int8_t* scores,size_t scoreCount)
{
    if (!scores || scoreCount!=360 || !InvokePolar(features,count)) return false;
    std::memcpy(scores,interpreter->output(0)->data.int8,360);
    return true;
}


bool CTfLiteClass::LoadInputImageBasis(CImageBasis *rs)
{
    #ifdef DEBUG_DETAIL_ON 
        LogFile.WriteHeapInfo("CTfLiteClass::LoadInputImageBasis - Start");
    #endif

    unsigned int w = rs->width;
    unsigned int h = rs->height;
    unsigned char red, green, blue;
//    ESP_LOGD(TAG, "Image: %s size: %d x %d\n", _fn.c_str(), w, h);

    input_i = 0;
    float* input_data_ptr = (interpreter->input(0))->data.f;

    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x)
            {
                red = rs->GetPixelColor(x, y, 0);
                green = rs->GetPixelColor(x, y, 1);
                blue = rs->GetPixelColor(x, y, 2);
                *(input_data_ptr) = (float) red;
                input_data_ptr++;
                *(input_data_ptr) = (float) green;
                input_data_ptr++;
                *(input_data_ptr) = (float) blue;
                input_data_ptr++;
            }

    #ifdef DEBUG_DETAIL_ON 
        LogFile.WriteHeapInfo("CTfLiteClass::LoadInputImageBasis - done");
    #endif

    return true;
}



bool CTfLiteClass::MakeAllocate()
{
    ResetInterpreter();
    if (!model || !tensor_arena || !MakeStaticResolver()) return false;

    #ifdef DEBUG_DETAIL_ON 
        LogFile.WriteHeapInfo("CTLiteClass::Alloc start");
    #endif

    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "CTfLiteClass::MakeAllocate");
    this->interpreter = new tflite::MicroInterpreter(this->model, resolver, this->tensor_arena, this->kTensorArenaSize);
    LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Trying to load the model. If it crashes here, it ist most likely due to a corrupted model!");

    if (this->interpreter) 
    {
        TfLiteStatus allocate_status = this->interpreter->AllocateTensors();
        if (allocate_status != kTfLiteOk) {
            LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "AllocateTensors() failed");
            ResetInterpreter();
            return false;
        }
    }
    else 
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "new tflite::MicroInterpreter failed");
        LogFile.WriteHeapInfo("CTfLiteClass::MakeAllocate-new tflite::MicroInterpreter failed");
        return false;
    }


    #ifdef DEBUG_DETAIL_ON 
        LogFile.WriteHeapInfo("CTLiteClass::Alloc done");
    #endif

    return true;
}


void CTfLiteClass::GetInputTensorSize()
{
#ifdef DEBUG_DETAIL_ON    
    float *zw = this->input;
    int test = sizeof(zw);
    ESP_LOGD(TAG, "Input Tensor Dimension: %d", test);
#endif
}


long CTfLiteClass::GetFileSize(std::string filename)
{
  struct stat stat_buf;
  long rc = -1;

  FILE *pFile = fopen(filename.c_str(), "rb"); // previously only "rb

  if (pFile != NULL)
  {
    rc = stat(filename.c_str(), &stat_buf);
    fclose(pFile);
  }
  
  return rc == 0 ? stat_buf.st_size : -1;
}


bool CTfLiteClass::ReadFileToModel(std::string _fn)
{
    ResetInterpreter();
    loadedModelBytes = 0;
    verifiedPolarModel = false;
    model = nullptr;
    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "CTfLiteClass::ReadFileToModel: " + _fn);
    
    long size = GetFileSize(_fn);

    if (size == -1)
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Model file doesn't exist: " + _fn + "!");
        return false;
    }
    else if(size <= 0 || size > MAX_MODEL_SIZE ||
            (polarWorkspaceOffset && static_cast<size_t>(size) > polarWorkspaceOffset)) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Unable to load model '" + _fn + "'! Invalid size or overlaps reserved workspace in PSRAM!");
        return false;
    }

    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "Loading Model " + _fn + " /size: " + std::to_string(size) + " bytes...");

#ifdef DEBUG_DETAIL_ON      
        LogFile.WriteHeapInfo("CTLiteClass::Alloc modelfile start");
#endif

    // The shared allocator grants the model region once per owner. Reusing its
    // pointer preserves the workspace tail and avoids a second acquisition while
    // the allocator is already in Digitization_Model state. A failed tensor
    // acquisition must never borrow or release another stage's allocation.
    if (!tensor_arena) return false;
    if (!modelfile) modelfile = (unsigned char*)psram_get_shared_model_memory();
  
    if (modelfile != NULL)
    {
        FILE *pFile = fopen(_fn.c_str(), "rb"); // previously only "rb
    
        if (pFile != NULL)
        {
          const size_t received = fread(modelfile, 1, size, pFile);
          const bool complete = received == static_cast<size_t>(size) &&
              fgetc(pFile) == EOF && !ferror(pFile);
          fclose(pFile);
          if (!complete) {
              LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Incomplete model read");
              return false;
          }
          loadedModelBytes = received;

#ifdef DEBUG_DETAIL_ON
          LogFile.WriteHeapInfo("CTLiteClass::Alloc modelfile successful");
#endif

          return true;
        }
        else
        {
          LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CTfLiteClass::ReadFileToModel: Model does not exist");
          return false;
        }
    }   
    else 
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "CTfLiteClass::ReadFileToModel: Can't allocate enough memory: " + std::to_string(size));
        LogFile.WriteHeapInfo("CTfLiteClass::ReadFileToModel");

        return false;
    }
}


bool CTfLiteClass::LoadModel(std::string _fn)
{
    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "CTfLiteClass::LoadModel");

    if (!ReadFileToModel(_fn.c_str())) {
      return false;
    }

    model = tflite::GetModel(modelfile);

    if(model == nullptr)     
      return false;
    
    return true;
}

bool CTfLiteClass::LoadFrozenPolarModel(std::string filename)
{
    // Preserve the original model contract until all routing consumers migrate.
    return LoadPolarModel(filename, polar::ModelRole::Secondary);
}

bool CTfLiteClass::LoadPolarModel(std::string filename, polar::ModelRole role)
{
    const auto* spec = polar::modelSpec(role);
    if (!spec) {
        ResetInterpreter(); model = nullptr; loadedModelBytes = 0;
        verifiedPolarModel = false;
        return false;
    }
    // Verify exact loaded bytes before interpreting the FlatBuffer. No fallback
    // to another role, similarly shaped model, or previously loaded interpreter.
    if (!ReadFileToModel(filename) || loadedModelBytes != spec->bytes) return false;
    uint8_t actual[32];
    if (mbedtls_sha256(modelfile, loadedModelBytes, actual, 0) != 0 ||
        std::memcmp(actual, spec->digest, sizeof(actual)) != 0) return false;
    model = tflite::GetModel(modelfile);
    verifiedPolarModel = model != nullptr;
    return verifiedPolarModel;
}

void* CTfLiteClass::GetPolarWorkspace(size_t bytes)
{
    if (!verifiedPolarModel || !modelfile || !bytes) return nullptr;
    const uintptr_t base = reinterpret_cast<uintptr_t>(modelfile);
    const uintptr_t start = (base + loadedModelBytes + 7u) & ~uintptr_t(7u);
    const size_t offset = polarWorkspaceOffset ? polarWorkspaceOffset : start - base;
    if (offset > MAX_MODEL_SIZE || bytes > MAX_MODEL_SIZE - offset) return nullptr;
    polarWorkspaceOffset = offset;
    return reinterpret_cast<void*>(base + offset);
}


CTfLiteClass::CTfLiteClass()
{
    this->model = nullptr;
    this->modelfile = NULL;
    this->interpreter = nullptr;
    this->input = nullptr;
    this->output = nullptr;
    this->kTensorArenaSize = TENSOR_ARENA_SIZE;
    this->tensor_arena = (uint8_t*)psram_get_shared_tensor_arena_memory();
}


CTfLiteClass::~CTfLiteClass()
{
  ResetInterpreter();

  if (tensor_arena) psram_free_shared_tensor_arena_and_model_memory();
}        
